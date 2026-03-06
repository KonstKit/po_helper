from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models import Project
from app.models.traceability import SyncTask
from app.tasks.jira_tasks import scheduled_jira_sync


@pytest.mark.asyncio
async def test_sync_project_returns_existing_fresh_running_sync(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    project = Project(name="WaBank", jira_key="WAB", status="active")
    db_session.add(project)
    await db_session.flush()

    started_at = datetime.now(timezone.utc)
    running_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=started_at,
        heartbeat_at=started_at,
        trigger="schedule",
    )
    db_session.add(running_task)
    await db_session.commit()

    dispatch_called = False

    def _unexpected_dispatch(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal dispatch_called
        dispatch_called = True
        raise AssertionError("sync should not dispatch while a fresh running task exists")

    monkeypatch.setattr("app.api.api_v1.endpoints.jira.sync_jira_project.delay", _unexpected_dispatch)

    response = await client.post("/api/v1/jira/projects/WAB/sync")

    assert response.status_code == 200
    assert dispatch_called is False
    data = response.json()
    assert data == {
        "status": "syncing",
        "message": "Jira sync is already running for project WAB",
        "project_id": project.id,
        "task_id": running_task.id,
        "sync_task_started_at": data["sync_task_started_at"],
        "method": "existing_running",
    }
    assert data["sync_task_started_at"].startswith(started_at.strftime("%Y-%m-%dT%H:%M:%S"))


@pytest.mark.asyncio
async def test_sync_project_ignores_stale_running_task_for_overlap_guard(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    project = Project(name="WaBank", jira_key="WAB", status="active")
    db_session.add(project)
    await db_session.flush()

    stale_started_at = datetime.now(timezone.utc) - timedelta(hours=1)
    stale_heartbeat_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_started_at,
        heartbeat_at=stale_heartbeat_at,
        trigger="schedule",
    )
    db_session.add(stale_task)
    await db_session.commit()

    monkeypatch.setattr("app.api.api_v1.endpoints.jira.settings.CELERY_ENABLED", True)
    monkeypatch.setattr("app.api.api_v1.endpoints.jira.settings.CELERY_USE_IN_DEV", True)

    def _fake_delay(project_key: str, project_id: int):  # type: ignore[no-untyped-def]
        assert project_key == "WAB"
        assert project_id == project.id
        return SimpleNamespace(id="celery-task-1")

    monkeypatch.setattr("app.api.api_v1.endpoints.jira.sync_jira_project.delay", _fake_delay)

    response = await client.post("/api/v1/jira/projects/WAB/sync")

    assert response.status_code == 200
    assert response.json() == {
        "status": "syncing",
        "message": "Started Celery sync for project WAB",
        "project_id": project.id,
        "task_id": "celery-task-1",
        "method": "celery",
    }


def test_scheduled_jira_sync_skips_projects_with_fresh_running_syncs(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fake_loader():
        return (
            [
                SimpleNamespace(id=1, jira_key="WAB"),
                SimpleNamespace(id=2, jira_key="ABC"),
            ],
            {1},
        )

    scheduled_calls: list[tuple[str, int, None, str]] = []

    def _run_async(coro):  # type: ignore[no-untyped-def]
        return asyncio.run(coro)

    def _fake_delay(project_key: str, project_id: int, channel_id, trigger: str):  # type: ignore[no-untyped-def]
        scheduled_calls.append((project_key, project_id, channel_id, trigger))

    monkeypatch.setattr("app.tasks.jira_tasks._load_projects_and_running_syncs", _fake_loader)
    monkeypatch.setattr("app.tasks.jira_tasks.run_async", _run_async)
    monkeypatch.setattr("app.tasks.jira_tasks.sync_jira_project.delay", _fake_delay)

    result = scheduled_jira_sync()

    assert result == {"status": "ok", "dispatched": 1, "skipped_running": 1}
    assert scheduled_calls == [("ABC", 2, None, "schedule")]
