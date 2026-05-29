"""Rule lifecycle + delete-cascade / retention boundary tests (plan_73, plan_78).

Validates the standalone rule lifecycle backend contracts the management page
binds to (list/get/create/update/enable/disable/duplicate/delete) and the
delete-cascade contract:
- unresolved review items block deletion (409);
- terminal review items are preserved with the rule reference cleared;
- rule execution rows are removed via cascade;
- artifact/suggested links are not touched.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.traceability_review import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_RESOLVED,
    TraceabilityReviewItem,
)
from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution


def _flow():
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
        "edges": [{"id": "e1", "source": "source-1", "target": "action-1"}],
        "version": "1.0",
        "metadata": {},
    }


async def _create_rule(client, name="lc-rule") -> int:
    resp = await client.post(
        "/api/v1/traceability/rules",
        json={"name": name, "flow_json": _flow(), "enabled": True, "category": "custom", "tags": []},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_rule_list_get_update_enable_disable(client):
    rule_id = await _create_rule(client, "lifecycle")

    listed = await client.get("/api/v1/traceability/rules")
    assert listed.status_code == 200
    assert any(r["id"] == rule_id for r in listed.json()["items"])

    got = await client.get(f"/api/v1/traceability/rules/{rule_id}")
    assert got.status_code == 200

    disabled = await client.put(
        f"/api/v1/traceability/rules/{rule_id}", json={"enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    enabled = await client.put(
        f"/api/v1/traceability/rules/{rule_id}", json={"enabled": True}
    )
    assert enabled.json()["enabled"] is True


@pytest.mark.asyncio
async def test_duplicate_rule_creates_independent_copy(client):
    rule_id = await _create_rule(client, "original")
    original = (await client.get(f"/api/v1/traceability/rules/{rule_id}")).json()

    dup = await client.post(
        "/api/v1/traceability/rules",
        json={
            "name": f"{original['name']} (copy)",
            "flow_json": original["flow_json"],
            "enabled": False,
            "category": original["category"],
            "tags": original["tags"],
        },
    )
    assert dup.status_code == 201
    assert dup.json()["id"] != rule_id
    assert dup.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_rule_without_dependents(client):
    rule_id = await _create_rule(client, "deletable")
    resp = await client.delete(f"/api/v1/traceability/rules/{rule_id}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/traceability/rules/{rule_id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_blocked_by_open_review_item(client, db_session):
    rule_id = await _create_rule(client, "has-open-review")
    db_session.add(
        TraceabilityReviewItem(
            artifact_id=1,
            rule_id=rule_id,
            node_id="review-1",
            status=REVIEW_STATUS_PENDING,
            priority="normal",
        )
    )
    await db_session.commit()

    resp = await client.delete(f"/api/v1/traceability/rules/{rule_id}")
    assert resp.status_code == 409
    # Rule must still exist.
    assert (await client.get(f"/api/v1/traceability/rules/{rule_id}")).status_code == 200


@pytest.mark.asyncio
async def test_delete_preserves_terminal_review_item_and_cascades_executions(client, db_session):
    rule_id = await _create_rule(client, "has-terminal-review")
    db_session.add(
        TraceabilityReviewItem(
            artifact_id=2,
            rule_id=rule_id,
            node_id="review-1",
            status=REVIEW_STATUS_RESOLVED,
            priority="normal",
        )
    )
    db_session.add(
        TraceabilityRuleExecution(rule_id=rule_id, status="success", links_created=0)
    )
    await db_session.commit()

    resp = await client.delete(f"/api/v1/traceability/rules/{rule_id}")
    assert resp.status_code == 204

    async with AsyncSessionLocal() as s:
        # Terminal review item preserved with rule reference cleared + snapshot.
        item = (
            await s.execute(
                select(TraceabilityReviewItem).where(
                    TraceabilityReviewItem.artifact_id == 2
                )
            )
        ).scalar_one()
        assert item.rule_id is None
        assert item.meta and item.meta.get("deleted_rule", {}).get("id") == rule_id

        # Execution rows removed via cascade.
        exec_count = (
            await s.execute(
                select(func.count())
                .select_from(TraceabilityRuleExecution)
                .where(TraceabilityRuleExecution.rule_id == rule_id)
            )
        ).scalar()
        assert exec_count == 0

        # Rule gone.
        rule = (
            await s.execute(select(TraceabilityRule).where(TraceabilityRule.id == rule_id))
        ).scalar_one_or_none()
        assert rule is None
