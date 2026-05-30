"""Regression: at-least-once sync redelivery must NOT create duplicate links.

Case #16. Sync/post-sync delivery is at-least-once, so a redelivered run can
re-invoke link creation. The guard that actually makes the rule-engine path
idempotent is the ``createLinkAction`` existence check (``_create_link``
short-circuits when a matching link already exists), which works regardless of
tenant. (The ``uq_artifact_link`` unique constraint is a second line of defence
*only when tenant_id is set* — under SQL NULL semantics a NULL tenant_id does
not collide, so it does not by itself dedupe single-tenant/local links. That is
why the engine's explicit existence check is the load-bearing guard.)

This module proves the path that matters under redelivery:

- Rule node: ``CreateLinkActionExecutor._create_link`` invoked twice across two
  separate sessions (mimicking redelivery) for the same (from, to, type) leaves
  exactly one ArtifactLink row — the second run's existence query sees the
  committed link and skips it with an "already exists" warning.

- Task layer: ``_execute_sync_complete_rules_async`` invoked twice for a project
  with one ``execute_on_sync_complete`` rule leaves the ArtifactLink count
  identical after the 2nd call as after the 1st (redelivery adds no links),
  even though a 2nd execution row is recorded — proving the task really ran
  again rather than being skipped.

Counts are read from a fresh ``AsyncSessionLocal()`` to avoid WAL snapshot
staleness, mirroring the other traceability test modules.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, SessionLocal
from app.models.project import Project
from app.models.traceability import Artifact, ArtifactLink
from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.create_link_action import (
    CreateLinkActionExecutor,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
async def _link_count(*, project_id: int | None = None) -> int:
    """Count ArtifactLink rows from a fresh session (avoids WAL staleness)."""
    async with AsyncSessionLocal() as s:
        stmt = select(func.count()).select_from(ArtifactLink)
        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)
        return (await s.execute(stmt)).scalar()


async def _execution_count(rule_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(TraceabilityRuleExecution)
                .where(TraceabilityRuleExecution.rule_id == rule_id)
            )
        ).scalar()


# ---------------------------------------------------------------------------
# Rule node: createLinkAction existence-check dedup (the redelivery guard)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def project_with_two_artifacts(db_session):
    """A project plus two artifacts (A, B) under it."""
    project = Project(jira_key="DUP", name="Dedup Project")
    db_session.add(project)
    await db_session.flush()

    art_a = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-A",
        title="Requirement A",
    )
    art_b = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-B",
        title="Requirement B",
    )
    db_session.add_all([art_a, art_b])
    await db_session.flush()
    project_id, a_id, b_id = project.id, art_a.id, art_b.id
    await db_session.commit()
    return project_id, a_id, b_id


def _create_link_via_node(a_id: int, b_id: int, link_type: str = "relates_to") -> int:
    """Run createLinkAction._create_link for (a->b) in a fresh sync session.

    Returns the ArtifactLink row count for the pair afterwards. Each call is its
    own committed session, mimicking a separate (redelivered) rule execution.
    """
    with SessionLocal() as db:
        source = db.query(Artifact).filter(Artifact.id == a_id).one()
        target = db.query(Artifact).filter(Artifact.id == b_id).one()
        context = ExecutionContext(rule_id=1, db=db, edges=[])
        CreateLinkActionExecutor()._create_link(source, target, link_type, context)
        db.commit()
        return (
            db.query(ArtifactLink)
            .filter(
                ArtifactLink.from_artifact_id == a_id,
                ArtifactLink.to_artifact_id == b_id,
                ArtifactLink.link_type == link_type,
            )
            .count()
        )


@pytest.mark.asyncio
async def test_rule_node_redelivery_creates_no_duplicate_link(project_with_two_artifacts):
    """The createLinkAction existence check is idempotent across redeliveries.

    Two separate sessions each run _create_link for the same (from, to, type)
    — the redelivery scenario. The first creates the link; the second sees the
    committed row and short-circuits, so exactly one row exists. This holds even
    though tenant_id is NULL (the unique constraint does not dedupe NULL-tenant
    rows; the engine's explicit existence check is what guarantees idempotency).
    """
    project_id, a_id, b_id = project_with_two_artifacts

    # First delivery creates the link.
    assert _create_link_via_node(a_id, b_id) == 1
    assert await _link_count(project_id=project_id) == 1

    # Redelivery: the existence check short-circuits — still exactly one row.
    assert _create_link_via_node(a_id, b_id) == 1
    assert await _link_count(project_id=project_id) == 1


# ---------------------------------------------------------------------------
# Task layer: _execute_sync_complete_rules_async redelivery idempotency
# ---------------------------------------------------------------------------
def _link_flow(a_id: int, b_id: int):
    """manualSource([A, B]) -> createLinkAction(self-link) — a flow that ACTUALLY
    creates a link. A single source carrying two artifacts plus
    allow_self_linking=true makes createLinkAction link A -> B (one link). A
    commitSource->createLinkAction flow would NOT create a link (single input,
    self-linking disabled by default), which is why the engine idempotency must
    be proven with this paired-self-link flow instead."""
    return {
        "nodes": [
            {
                "id": "src",
                "type": "manualSource",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Manual", "config": {"artifact_ids": [a_id, b_id]}},
            },
            {
                "id": "act",
                "type": "createLinkAction",
                "position": {"x": 200, "y": 0},
                "data": {
                    "label": "Create Link",
                    "config": {"link_type": "relates_to", "allow_self_linking": True},
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "src", "target": "act", "sourceHandle": "output", "targetHandle": "input"}
        ],
        "version": "1.0",
        "metadata": {},
    }


@pytest_asyncio.fixture
async def sync_complete_link_rule(db_session):
    """Project + two artifacts + one execute_on_sync_complete rule whose flow
    genuinely creates a link (manualSource[A,B] -> createLinkAction self-link)."""
    project = Project(jira_key="SYN", name="Sync Project")
    db_session.add(project)
    await db_session.flush()
    art_a = Artifact(
        project_id=project.id, type="requirement", source="internal",
        external_id="REQ-A", title="Requirement A",
    )
    art_b = Artifact(
        project_id=project.id, type="requirement", source="internal",
        external_id="REQ-B", title="Requirement B",
    )
    db_session.add_all([art_a, art_b])
    await db_session.flush()
    rule = TraceabilityRule(
        name="sync-complete link rule",
        flow_json=_link_flow(art_a.id, art_b.id),
        enabled=True,
        execute_on_sync_complete=True,
        project_id=project.id,
    )
    db_session.add(rule)
    await db_session.commit()
    return project.id, rule.id


@pytest.mark.asyncio
async def test_sync_complete_redelivery_creates_no_new_links(sync_complete_link_rule):
    """A redelivered post-sync run records a new execution but adds NO new links.

    The flow really creates a link on the first run (count 1). The
    createLinkAction existence check makes the engine idempotent: the second
    (redelivered) run sees the link already present and short-circuits, so the
    count stays 1 while the execution count advances 1 -> 2 (proving the task
    genuinely ran again rather than being skipped).
    """
    from app.tasks.traceability_tasks import _execute_sync_complete_rules_async

    project_id, rule_id = sync_complete_link_rule

    # First delivery: the rule creates exactly one link.
    results_1 = await _execute_sync_complete_rules_async(
        project_id, source="jira", trigger="sync"
    )
    assert len(results_1) == 1
    assert results_1[0]["rule_id"] == rule_id
    assert await _execution_count(rule_id) == 1
    assert await _link_count(project_id=project_id) == 1

    # Redelivery (at-least-once): same project, same sync-complete rule.
    results_2 = await _execute_sync_complete_rules_async(
        project_id, source="jira", trigger="sync"
    )
    assert len(results_2) == 1
    assert results_2[0]["rule_id"] == rule_id

    # A second execution row IS recorded (the task really ran again)...
    assert await _execution_count(rule_id) == 2
    # ...but the link was NOT duplicated.
    assert await _link_count(project_id=project_id) == 1
