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
        "sync_task_id": running_task.id,
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

    def _fake_delay(
        project_key: str,
        project_id: int,
        channel_id,
        trigger: str,
        sync_task_id: int,
    ):  # type: ignore[no-untyped-def]
        assert project_key == "WAB"
        assert project_id == project.id
        assert channel_id is None
        assert trigger == "manual"
        assert isinstance(sync_task_id, int)
        return SimpleNamespace(id="celery-task-1")

    monkeypatch.setattr("app.api.api_v1.endpoints.jira.sync_jira_project.delay", _fake_delay)

    response = await client.post("/api/v1/jira/projects/WAB/sync")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "status": "syncing",
        "message": "Started Celery sync for project WAB",
        "project_id": project.id,
        "task_id": "celery-task-1",
        "sync_task_id": data["sync_task_id"],
        "sync_task_started_at": data["sync_task_started_at"],
        "method": "celery",
    }
    assert isinstance(data["sync_task_id"], int)
    assert isinstance(data["sync_task_started_at"], str)


@pytest.mark.asyncio
async def test_concurrent_manual_sync_dispatches_only_once(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    project = Project(name="WaBank", jira_key="WAB", status="active")
    db_session.add(project)
    await db_session.commit()

    monkeypatch.setattr("app.api.api_v1.endpoints.jira.settings.CELERY_ENABLED", True)
    monkeypatch.setattr("app.api.api_v1.endpoints.jira.settings.CELERY_USE_IN_DEV", True)

    async def _fake_call_jira(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return {"key": "WAB", "name": "WaBank"}

    delay_calls: list[tuple[str, int, None, str, int]] = []

    def _fake_delay(
        project_key: str,
        project_id: int,
        channel_id,
        trigger: str,
        sync_task_id: int,
    ):  # type: ignore[no-untyped-def]
        delay_calls.append((project_key, project_id, channel_id, trigger, sync_task_id))
        return SimpleNamespace(id=f"celery-task-{len(delay_calls)}")

    monkeypatch.setattr("app.api.api_v1.endpoints.jira._call_jira", _fake_call_jira)
    monkeypatch.setattr("app.api.api_v1.endpoints.jira.sync_jira_project.delay", _fake_delay)

    first_response, second_response = await asyncio.gather(
        client.post("/api/v1/jira/projects/WAB/sync"),
        client.post("/api/v1/jira/projects/WAB/sync"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(delay_calls) == 1

    methods = {first_response.json()["method"], second_response.json()["method"]}
    assert methods == {"celery", "existing_running"}


def test_scheduled_jira_sync_skips_projects_with_fresh_running_syncs(
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fake_loader():
        return [SimpleNamespace(id=1, jira_key="WAB"), SimpleNamespace(id=2, jira_key="ABC")]

    async def _fake_reserve(project_id: int):
        if project_id == 1:
            return (101, False)
        return (202, True)

    scheduled_calls: list[tuple[str, int, None, str, int]] = []

    def _run_async(coro):  # type: ignore[no-untyped-def]
        return asyncio.run(coro)

    def _fake_delay(
        project_key: str,
        project_id: int,
        channel_id,
        trigger: str,
        sync_task_id: int,
    ):  # type: ignore[no-untyped-def]
        scheduled_calls.append((project_key, project_id, channel_id, trigger, sync_task_id))

    monkeypatch.setattr("app.tasks.jira_tasks._load_active_projects", _fake_loader)
    monkeypatch.setattr("app.tasks.jira_tasks._reserve_scheduled_sync_lease", _fake_reserve)
    monkeypatch.setattr("app.tasks.jira_tasks.run_async", _run_async)
    monkeypatch.setattr("app.tasks.jira_tasks.sync_jira_project.delay", _fake_delay)

    result = scheduled_jira_sync()

    assert result == {
        "status": "ok",
        "dispatched": 1,
        "skipped_running": 1,
        "dispatch_failed": 0,
    }
    assert scheduled_calls == [("ABC", 2, None, "schedule", 202)]
