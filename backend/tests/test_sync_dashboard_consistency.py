from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Project, Sprint, Task
from app.services.jira_service import jira_service
from app.services.sync.project_sync_orchestrator import ProjectSyncOrchestrator


def _has_velocity_data_or_fallback(payload: dict) -> bool:
    if payload.get("sprint_velocities"):
        return True
    return (
        payload.get("sprints_analyzed") == 0
        and payload.get("velocity_trend") == "insufficient_data"
    )


def _has_burndown_data_or_fallback(payload: dict) -> bool:
    if payload.get("ideal_burndown") and payload.get("actual_burndown"):
        return True
    return payload.get("ideal_burndown") == [] and payload.get("actual_burndown") == []


def _has_wip_data_or_fallback(payload: dict) -> bool:
    if payload.get("assignees"):
        return True
    return payload.get("total_active") == 0 and payload.get("assignees") == []


@pytest.mark.asyncio
async def test_dashboard_data_is_consistent_after_sync(
    client, db_session, monkeypatch: pytest.MonkeyPatch
):
    project = Project(jira_key="SYNC", name="Sync Dashboard Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    now = datetime.now(timezone.utc)
    sprint_start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    sprint_end = (now + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)

    async def _fake_async_get_project_issues(project_key: str):
        assert project_key == "SYNC"
        return [
            {
                "id": "1001",
                "key": "SYNC-1",
                "fields": {
                    "summary": "Done issue",
                    "status": {"name": "Done"},
                    "timeoriginalestimate": 14400,
                    "resolutiondate": (now - timedelta(days=1)).isoformat(),
                    "created": (now - timedelta(days=5)).isoformat(),
                    "updated": (now - timedelta(days=1)).isoformat(),
                    "assignee": {"emailAddress": "alice@example.com", "displayName": "Alice"},
                },
            },
            {
                "id": "1002",
                "key": "SYNC-2",
                "fields": {
                    "summary": "Active issue",
                    "status": {"name": "In Progress"},
                    "timeoriginalestimate": 7200,
                    "created": (now - timedelta(days=3)).isoformat(),
                    "updated": now.isoformat(),
                    "assignee": {"emailAddress": "bob@example.com", "displayName": "Bob"},
                },
            },
        ]

    async def _fake_async_get_issue_worklogs(_issue_key: str):
        return []

    monkeypatch.setattr(jira_service, "async_get_project_issues", _fake_async_get_project_issues)
    monkeypatch.setattr(jira_service, "async_get_issue_worklogs", _fake_async_get_issue_worklogs)
    monkeypatch.setattr(
        jira_service,
        "list_boards_for_project",
        lambda _project_key: [{"id": 10, "name": "Main Scrum"}],
    )
    monkeypatch.setattr(
        jira_service,
        "list_sprints",
        lambda _board_id: [
            {
                "id": 200,
                "name": "Sprint 200",
                "state": "closed",
                "startDate": sprint_start.isoformat(),
                "endDate": sprint_end.isoformat(),
                "completeDate": (now - timedelta(hours=12)).isoformat(),
            }
        ],
    )
    monkeypatch.setattr(
        jira_service,
        "list_issues_in_sprint",
        lambda _sprint_id: [{"key": "SYNC-1"}, {"key": "SYNC-2"}],
    )
    # Skip runtime bootstrap logic in the test by simulating connected Jira client.
    monkeypatch.setattr(jira_service, "base_url", "https://jira.example.com", raising=False)
    monkeypatch.setattr(jira_service, "auth", object(), raising=False)

    orchestrator = ProjectSyncOrchestrator()
    sync_result = await orchestrator.sync_project("SYNC", project.id, trigger="manual")

    assert sync_result.success is True
    assert sync_result.total_issues == 2

    synced_tasks = (
        (
            await db_session.execute(
                select(Task).where(Task.project_id == project.id).order_by(Task.key)
            )
        )
        .scalars()
        .all()
    )
    assert [task.key for task in synced_tasks] == ["SYNC-1", "SYNC-2"]
    assert all(task.sprint_id is not None for task in synced_tasks)
    assert len({task.sprint_id for task in synced_tasks}) == 1

    sprint_id = synced_tasks[0].sprint_id
    assert sprint_id is not None

    synced_sprint = (
        await db_session.execute(select(Sprint).where(Sprint.id == sprint_id))
    ).scalar_one()
    assert synced_sprint.commitment is not None
    assert synced_sprint.completed is not None
    assert synced_sprint.velocity is not None
    assert synced_sprint.commitment >= 0
    assert synced_sprint.completed >= 0
    assert synced_sprint.velocity == pytest.approx(synced_sprint.completed)

    velocity_response = await client.get(
        f"/api/v1/analytics/projects/{project.id}/velocity",
        params={"sprints_count": 3},
    )
    burndown_response = await client.get(
        f"/api/v1/analytics/projects/{project.id}/burndown",
        params={"sprint_id": sprint_id},
    )
    wip_response = await client.get(f"/api/v1/analytics/sprints/{sprint_id}/wip-status")

    assert velocity_response.status_code == 200
    assert burndown_response.status_code == 200
    assert wip_response.status_code == 200

    velocity_payload = velocity_response.json()
    burndown_payload = burndown_response.json()
    wip_payload = wip_response.json()

    assert _has_velocity_data_or_fallback(velocity_payload)
    assert _has_burndown_data_or_fallback(burndown_payload)
    assert _has_wip_data_or_fallback(wip_payload)

    # This test data is expected to produce non-empty dashboard widgets.
    assert velocity_payload["sprint_velocities"]
    assert burndown_payload["ideal_burndown"]
    assert burndown_payload["actual_burndown"]
    assert wip_payload["assignees"]
