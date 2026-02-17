from __future__ import annotations

import pytest


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
                "data": {
                    "label": "Create Link",
                    "config": {"link_type": "relates_to", "bidirectional": False},
                },
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


@pytest.mark.asyncio
async def test_rule_webhook_and_schedule_flow(client):
    # Create rule
    create_payload = {
        "name": "automation-e2e",
        "description": "automation test",
        "flow_json": _simple_flow(),
        "enabled": True,
        "category": "custom",
        "tags": [],
    }
    created = await client.post("/api/v1/traceability/rules", json=create_payload)
    assert created.status_code == 201
    rule = created.json()
    rule_id = rule["id"]

    # Enable webhook and capture token
    enabled = await client.post(f"/api/v1/traceability/rules/{rule_id}/webhook/enable")
    assert enabled.status_code == 200
    enabled_body = enabled.json()
    token = enabled_body["webhook_token"]
    assert token
    assert enabled_body["trigger_on_webhook"] is True

    # Execute via webhook token
    executed = await client.post(f"/api/v1/traceability/webhook/{token}")
    assert executed.status_code == 200
    exec_body = executed.json()
    assert exec_body["rule_id"] == rule_id
    assert "execution_id" in exec_body

    # Disable webhook and ensure token no longer works
    disabled = await client.post(f"/api/v1/traceability/rules/{rule_id}/webhook/disable")
    assert disabled.status_code == 200
    assert disabled.json()["trigger_on_webhook"] is False

    after_disable = await client.post(f"/api/v1/traceability/webhook/{token}")
    assert after_disable.status_code == 404

    # Update schedule
    schedule = await client.put(
        f"/api/v1/traceability/rules/{rule_id}/schedule",
        json={"schedule_cron": "*/15 * * * *", "schedule_enabled": True},
    )
    assert schedule.status_code == 200
    sched_body = schedule.json()
    assert sched_body["rule_id"] == rule_id
    assert sched_body["schedule_enabled"] is True
    assert sched_body["schedule_cron"] == "*/15 * * * *"
    assert sched_body["next_scheduled_run"] is not None
