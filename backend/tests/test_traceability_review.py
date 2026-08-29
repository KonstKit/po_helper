"""Tests for the traceability manual-review queue (plan_70).

Covers three layers:
- Engine end-to-end: queueReviewAction persists durable review items with
  deduplication across reruns (sync engine).
- Service: status-graph enforcement for transitions.
- API: list/get/claim/resolve/reject/reopen lifecycle, RBAC for reopen,
  invalid-transition and validation errors, and audit records.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, SessionLocal
from app.models.project import Project
from app.models.traceability import Artifact, AuditLog
from app.models.traceability_review import (
    REVIEW_STATUS_CLAIMED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_RESOLVED,
    TraceabilityReviewItem,
)
from app.models.traceability_rule import TraceabilityRule
from app.services.rule_execution_engine import RuleExecutionEngine
from app.services.traceability.review_service import (
    ReviewTransitionError,
    persist_review_candidates_sync,
    transition_review_item,
)


def _review_flow(artifact_id: int, *, priority: str = "high", reason: str = "needs eyes"):
    return {
        "nodes": [
            {
                "id": "src",
                "type": "manualSource",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Source", "config": {"artifact_ids": [artifact_id]}},
            },
            {
                "id": "review-1",
                "type": "queueReviewAction",
                "position": {"x": 200, "y": 0},
                "data": {"label": "Review", "config": {"priority": priority, "reason": reason}},
            },
        ],
        "edges": [{"id": "e1", "source": "src", "target": "review-1"}],
    }


def _seed_rule_with_artifact(priority: str = "high", reason: str = "needs eyes"):
    """Create a project, artifact and a manualSource->queueReviewAction rule.

    Returns (rule_id, artifact_id, project_id) using the sync session that the
    execution engine also uses.
    """
    with SessionLocal() as db:
        project = Project(name="Review Proj", jira_key="REV")
        db.add(project)
        db.flush()
        artifact = Artifact(
            project_id=project.id,
            type="requirement",
            source="internal",
            external_id="REQ-1",
            title="Login requirement",
        )
        db.add(artifact)
        db.flush()
        rule = TraceabilityRule(
            name="Queue review rule",
            flow_json=_review_flow(artifact.id, priority=priority, reason=reason),
            enabled=True,
            project_id=project.id,
        )
        db.add(rule)
        db.commit()
        return rule.id, artifact.id, project.id


# ---------------------------------------------------------------------------
# Engine end-to-end
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_queue_review_action_persists_durable_item():
    rule_id, artifact_id, project_id = _seed_rule_with_artifact()

    with SessionLocal() as db:
        result = RuleExecutionEngine(db).execute_rule(rule_id)

    assert result["status"] == "success"
    assert result["review_items_created"] == 1
    assert result["review_items_updated"] == 0

    with SessionLocal() as db:
        items = db.query(TraceabilityReviewItem).all()
        assert len(items) == 1
        item = items[0]
        assert item.artifact_id == artifact_id
        assert item.rule_id == rule_id
        assert item.project_id == project_id
        assert item.node_id == "review-1"
        assert item.status == REVIEW_STATUS_PENDING
        assert item.priority == "high"
        assert item.reason == "needs eyes"
        assert item.rule_execution_id == result["execution_id"]
        assert item.meta and item.meta.get("external_id") == "REQ-1"


@pytest.mark.asyncio
async def test_rerun_dedups_open_review_item():
    rule_id, _artifact_id, _project_id = _seed_rule_with_artifact()

    with SessionLocal() as db:
        RuleExecutionEngine(db).execute_rule(rule_id)
    with SessionLocal() as db:
        second = RuleExecutionEngine(db).execute_rule(rule_id)

    # Second run must refresh the open item, not create a duplicate.
    assert second["review_items_created"] == 0
    assert second["review_items_updated"] == 1

    with SessionLocal() as db:
        items = db.query(TraceabilityReviewItem).all()
        assert len(items) == 1
        assert items[0].rule_execution_id == second["execution_id"]


@pytest.mark.asyncio
async def test_resolved_item_does_not_block_new_open_item_on_rerun():
    rule_id, _artifact_id, _project_id = _seed_rule_with_artifact()

    with SessionLocal() as db:
        RuleExecutionEngine(db).execute_rule(rule_id)
    # Resolve the first item so it leaves the open dedup scope.
    with SessionLocal() as db:
        item = db.query(TraceabilityReviewItem).one()
        item.status = REVIEW_STATUS_RESOLVED
        db.commit()
    with SessionLocal() as db:
        rerun = RuleExecutionEngine(db).execute_rule(rule_id)

    assert rerun["review_items_created"] == 1
    with SessionLocal() as db:
        statuses = sorted(i.status for i in db.query(TraceabilityReviewItem).all())
        assert statuses == [REVIEW_STATUS_PENDING, REVIEW_STATUS_RESOLVED]


def test_persist_dedups_duplicate_candidates_in_one_batch():
    """Two candidates with the same dedup key in a SINGLE batch must collapse to
    one row instead of both inserting and violating the partial unique index at
    flush. Regression for the autoflush=False same-batch duplicate crash that
    aborted the whole rule run."""
    with SessionLocal() as db:
        project = Project(name="Dedup Proj", jira_key="DUP")
        db.add(project)
        db.flush()
        artifact = Artifact(
            project_id=project.id,
            type="requirement",
            source="internal",
            external_id="REQ-DUP",
            title="Dup",
        )
        db.add(artifact)
        db.flush()
        rule = TraceabilityRule(
            name="Dedup rule",
            flow_json=_review_flow(artifact.id),
            enabled=True,
            project_id=project.id,
        )
        db.add(rule)
        db.flush()

        candidate = {
            "artifact_id": artifact.id,
            "project_id": project.id,
            "node_id": "review-1",
            "priority": "high",
            "reason": "dup",
            "meta": {"external_id": "REQ-DUP"},
        }
        # Two distinct dicts with the same dedup key, as the node would emit for
        # the same artifact arriving twice in one run.
        summary = persist_review_candidates_sync(
            db,
            rule_id=rule.id,
            execution_id=None,
            candidates=[candidate, dict(candidate)],
        )
        db.commit()

        assert summary == {"created": 1, "updated": 0}
        rows = (
            db.query(TraceabilityReviewItem)
            .filter(TraceabilityReviewItem.artifact_id == artifact.id)
            .all()
        )
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Service-level status graph
# ---------------------------------------------------------------------------
def test_transition_graph_allows_claim_then_resolve():
    item = TraceabilityReviewItem(
        artifact_id=1, node_id="n", status=REVIEW_STATUS_PENDING, priority="normal"
    )
    transition_review_item(item, target_status=REVIEW_STATUS_CLAIMED, actor_id=7)
    assert item.status == REVIEW_STATUS_CLAIMED
    assert item.assigned_to_id == 7

    transition_review_item(item, target_status=REVIEW_STATUS_RESOLVED, actor_id=7, note="done")
    assert item.status == REVIEW_STATUS_RESOLVED
    assert item.resolved_by_id == 7
    assert item.resolved_at is not None
    assert item.meta["transition_notes"][-1]["note"] == "done"


def test_transition_graph_rejects_illegal_move():
    item = TraceabilityReviewItem(
        artifact_id=1, node_id="n", status=REVIEW_STATUS_RESOLVED, priority="normal"
    )
    with pytest.raises(ReviewTransitionError):
        # resolved -> claimed is not allowed (only reopen to pending).
        transition_review_item(item, target_status=REVIEW_STATUS_CLAIMED, actor_id=1)


def test_reopen_from_terminal_clears_resolution():
    item = TraceabilityReviewItem(
        artifact_id=1,
        node_id="n",
        status=REVIEW_STATUS_REJECTED,
        priority="normal",
        resolved_by_id=3,
        assigned_to_id=3,
    )
    transition_review_item(item, target_status=REVIEW_STATUS_PENDING, actor_id=9, note="reopen")
    assert item.status == REVIEW_STATUS_PENDING
    assert item.resolved_by_id is None
    assert item.assigned_to_id is None


def test_release_claimed_item_clears_assignee():
    """Releasing a claimed item back to pending must clear assigned_to_id, so it
    is not left looking claimed while sitting in the open (unassigned) queue."""
    item = TraceabilityReviewItem(
        artifact_id=1,
        node_id="n",
        status=REVIEW_STATUS_CLAIMED,
        priority="normal",
        assigned_to_id=7,
    )
    transition_review_item(item, target_status=REVIEW_STATUS_PENDING, actor_id=7)
    assert item.status == REVIEW_STATUS_PENDING
    assert item.assigned_to_id is None


# ---------------------------------------------------------------------------
# API lifecycle
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def seeded_item(db_session):
    """Insert a project-less review item directly (FK enforcement off on SQLite)."""
    item = TraceabilityReviewItem(
        project_id=None,
        artifact_id=101,
        rule_id=None,
        node_id="review-1",
        status=REVIEW_STATUS_PENDING,
        priority="normal",
        reason="please review",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest.mark.asyncio
async def test_list_and_get_review_items(client, seeded_item, auth_headers):
    resp = await client.get("/api/v1/traceability/review-items", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(i["id"] == seeded_item.id for i in body["items"])

    detail = await client.get(
        f"/api/v1/traceability/review-items/{seeded_item.id}", headers=auth_headers
    )
    assert detail.status_code == 200
    assert detail.json()["reason"] == "please review"


@pytest.mark.asyncio
async def test_get_missing_review_item_returns_404(client, auth_headers):
    resp = await client.get("/api/v1/traceability/review-items/999999", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_rejects_invalid_status(client, auth_headers):
    resp = await client.get("/api/v1/traceability/review-items?status=bogus", headers=auth_headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_rejects_invalid_priority(client, auth_headers):
    resp = await client.get(
        "/api/v1/traceability/review-items?priority=bogus", headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_claim_resolve_lifecycle_and_audit(client, db_session, seeded_item, auth_headers):
    claim = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/claim", headers=auth_headers
    )
    assert claim.status_code == 200
    assert claim.json()["status"] == REVIEW_STATUS_CLAIMED

    resolve = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/resolve",
        json={"note": "handled"},
        headers=auth_headers,
    )
    assert resolve.status_code == 200
    body = resolve.json()
    assert body["status"] == REVIEW_STATUS_RESOLVED
    assert body["resolved_by_id"] is not None
    assert body["resolved_at"] is not None

    audits = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.entity_type == "traceability_review_item")
            )
        )
        .scalars()
        .all()
    )
    actions = {a.action for a in audits}
    assert {"review_claim", "review_resolve"}.issubset(actions)


@pytest.mark.asyncio
async def test_double_resolve_returns_409(client, seeded_item, auth_headers):
    first = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/resolve", headers=auth_headers
    )
    assert first.status_code == 200
    second = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/resolve", headers=auth_headers
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_reject_then_reopen(client, seeded_item, auth_headers):
    reject = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/reject",
        json={"note": "not relevant"},
        headers=auth_headers,
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == REVIEW_STATUS_REJECTED

    # The default test user is a superuser, so reopen is permitted.
    reopen = await client.post(
        f"/api/v1/traceability/review-items/{seeded_item.id}/reopen", headers=auth_headers
    )
    assert reopen.status_code == 200
    assert reopen.json()["status"] == REVIEW_STATUS_PENDING


class _ManagerOnlyUser:
    """A traceability manager who is NOT an administrator/superuser."""

    id = 4242
    email = "manager@example.com"
    username = "manager"
    full_name = "Manager"
    is_active = True
    is_superuser = False
    mfa_enabled = False

    def has_permission(self, permission: str) -> bool:
        # Has manage/view, but explicitly NOT admin.
        return permission in {"traceability:view", "traceability:manage"}

    def has_role(self, _role: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_reopen_forbidden_for_non_admin_manager(db_session, client, auth_headers):
    """RBAC: reopening a terminal item requires administrator rights. A plain
    traceability manager (can claim/resolve/reject) must get 403 on reopen."""
    from app.api.deps import get_current_user
    from app.main import app

    # Seed a resolved (terminal) item.
    item = TraceabilityReviewItem(
        project_id=None,
        artifact_id=777,
        node_id="review-1",
        status=REVIEW_STATUS_RESOLVED,
        priority="normal",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    async def _manager():
        return _ManagerOnlyUser()

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _manager
    try:
        resp = await client.post(
            f"/api/v1/traceability/review-items/{item.id}/reopen", headers=auth_headers
        )
        assert resp.status_code == 403
    finally:
        if original is not None:
            app.dependency_overrides[get_current_user] = original
        else:
            app.dependency_overrides.pop(get_current_user, None)

    # Item remains terminal (the forbidden transition did not apply).
    async with AsyncSessionLocal() as s:
        status = (
            await s.execute(
                select(TraceabilityReviewItem.status).where(TraceabilityReviewItem.id == item.id)
            )
        ).scalar_one()
        assert status == REVIEW_STATUS_RESOLVED
