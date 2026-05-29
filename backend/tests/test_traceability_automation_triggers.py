"""Scheduled / webhook / post-sync execution validation (plan_76).

Scope: unit + mocked trigger coverage that runs in-session. Live worker, broker
and scheduler validation is handed off (see docs/TRACEABILITY_AUTOMATION_VALIDATION.md).
Scheduler due-selection and invalid-cron disabling are already covered by
test_traceability_rule_builder_contracts.py; this module covers webhook token
authorization, execution-history recording, and post-sync idempotency.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.traceability import Artifact
from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution


def _simple_flow():
    return {
        "nodes": [
            {
                "id": "source-1",
                "type": "commitSource",
                "position": {"x": 0, "y": 0},
                "data": {"label": "Commits", "filters": {}},
            },
            {
                "id": "action-1",
                "type": "createLinkAction",
                "position": {"x": 200, "y": 0},
                "data": {"label": "Create Link", "config": {"link_type": "relates_to"}},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "source-1",
                "target": "action-1",
                "sourceHandle": "output",
                "targetHandle": "input",
            }
        ],
        "version": "1.0",
        "metadata": {},
    }


async def _create_rule_via_api(client, name: str = "wh-rule") -> int:
    payload = {
        "name": name,
        "flow_json": _simple_flow(),
        "enabled": True,
        "category": "custom",
        "tags": [],
    }
    resp = await client.post("/api/v1/traceability/rules", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Webhook authorization
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_webhook_invalid_token_returns_404(client):
    resp = await client.post("/api/v1/traceability/webhook/not-a-real-token")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_executes_with_valid_token_and_records_history(client):
    rule_id = await _create_rule_via_api(client, "wh-valid")
    enabled = await client.post(f"/api/v1/traceability/rules/{rule_id}/webhook/enable")
    token = enabled.json()["webhook_token"]

    executed = await client.post(f"/api/v1/traceability/webhook/{token}")
    assert executed.status_code == 200
    assert executed.json()["rule_id"] == rule_id

    history = await client.get(f"/api/v1/traceability/rules/{rule_id}/executions")
    assert history.status_code == 200
    body = history.json()
    assert body["total"] >= 1
    assert body["items"][0]["status"] in {"success", "failed"}


@pytest.mark.asyncio
async def test_webhook_on_disabled_rule_returns_400(client, db_session):
    rule_id = await _create_rule_via_api(client, "wh-disabled")
    enabled = await client.post(f"/api/v1/traceability/rules/{rule_id}/webhook/enable")
    token = enabled.json()["webhook_token"]

    # Disable the rule itself (keep webhook trigger on).
    await client.put(
        f"/api/v1/traceability/rules/{rule_id}",
        json={"enabled": False},
    )

    resp = await client.post(f"/api/v1/traceability/webhook/{token}")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Post-sync execution + idempotency
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def sync_complete_rule(db_session):
    project = Project(jira_key="SYN", name="Sync Project")
    db_session.add(project)
    await db_session.flush()
    # An artifact so the (commitSource) flow has a clean run.
    db_session.add(
        Artifact(
            project_id=project.id,
            type="commit",
            source="github",
            external_id="abc123",
            title="commit",
        )
    )
    rule = TraceabilityRule(
        name="sync-complete rule",
        flow_json=_simple_flow(),
        enabled=True,
        execute_on_sync_complete=True,
        project_id=project.id,
    )
    db_session.add(rule)
    await db_session.commit()
    return project.id, rule.id


async def _execution_count(rule_id: int) -> int:
    async with AsyncSessionLocal() as s:
        return (
            await s.execute(
                select(func.count())
                .select_from(TraceabilityRuleExecution)
                .where(TraceabilityRuleExecution.rule_id == rule_id)
            )
        ).scalar()


@pytest.mark.asyncio
async def test_sync_complete_rule_runs_once_per_event(sync_complete_rule):
    from app.tasks.traceability_tasks import _execute_sync_complete_rules_async

    project_id, rule_id = sync_complete_rule

    results = await _execute_sync_complete_rules_async(project_id, source="jira", trigger="sync")
    assert len(results) == 1
    assert results[0]["rule_id"] == rule_id
    # Exactly one execution recorded for this one sync event.
    assert await _execution_count(rule_id) == 1

    # A second sync event triggers exactly one more execution (one per event).
    await _execute_sync_complete_rules_async(project_id, source="jira", trigger="sync")
    assert await _execution_count(rule_id) == 2


@pytest.mark.asyncio
async def test_post_sync_noop_when_no_artifact_delta(sync_complete_rule):
    from app.services.traceability.post_sync import run_traceability_post_sync

    project_id, rule_id = sync_complete_rule

    # No artifact delta → post-sync must short-circuit and run no rules.
    await run_traceability_post_sync(project_id, artifact_delta=0, source="jira", trigger="sync")
    assert await _execution_count(rule_id) == 0

    # None project → also a no-op.
    await run_traceability_post_sync(None, artifact_delta=5, source="jira", trigger="sync")
    assert await _execution_count(rule_id) == 0
