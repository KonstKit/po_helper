from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.api.deps import get_current_user
from app.main import app
from app.models import Project
from app.models import Permissions
from app.models.traceability import SyncTask
from app.services.sync_tracking import (
    STALE_RUNNING_ERROR_CODE,
    finish_sync_task,
    recover_stale_running_sync_tasks,
    start_sync_task,
    touch_sync_task_heartbeat,
)


class _TraceabilityViewerUser:
    id = 42
    email = "reader@example.com"
    username = "reader"
    full_name = "Reader User"
    is_active = True
    is_superuser = False

    def has_permission(self, permission: str) -> bool:
        return permission == Permissions.TRACEABILITY_VIEW

    def has_role(self, _role: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_recover_stale_running_sync_tasks_marks_task_failed(db_session):
    project = Project(jira_key="RECOV", name="Recovery Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    now = datetime.now(timezone.utc)
    stale_at = now - timedelta(hours=3)

    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    fresh_task = SyncTask(
        project_id=project.id,
        task_type="confluence_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=now,
        trigger="manual",
    )
    db_session.add_all([stale_task, fresh_task])
    await db_session.commit()

    recovered_count = await recover_stale_running_sync_tasks(db_session, ttl_seconds=3600)
    await db_session.commit()

    assert recovered_count == 1

    recovered_stale_task = await db_session.get(SyncTask, stale_task.id)
    current_fresh_task = await db_session.get(SyncTask, fresh_task.id)

    assert recovered_stale_task is not None
    assert recovered_stale_task.status == "failed"
    assert recovered_stale_task.error_code == STALE_RUNNING_ERROR_CODE
    assert recovered_stale_task.error_message is not None
    assert "heartbeat exceeded TTL" in recovered_stale_task.error_message
    assert recovered_stale_task.finished_at is not None

    assert current_fresh_task is not None
    assert current_fresh_task.status == "running"


@pytest.mark.asyncio
async def test_sync_task_heartbeat_lifecycle(db_session):
    task = await start_sync_task(
        db_session,
        task_type="jira_sync",
        project_id=None,
        source_id=None,
        trigger="manual",
    )
    await db_session.commit()

    # Make the initial timestamp older to validate heartbeat advancement.
    old_start = datetime.now(timezone.utc) - timedelta(minutes=10)
    task.started_at = old_start
    task.heartbeat_at = old_start
    await db_session.commit()

    await touch_sync_task_heartbeat(db_session, task.id, item_counts={"step": "worklogs"})
    await db_session.commit()

    task_after_heartbeat = await db_session.get(SyncTask, task.id)
    assert task_after_heartbeat is not None
    assert task_after_heartbeat.heartbeat_at is not None
    assert task_after_heartbeat.heartbeat_at > old_start
    assert task_after_heartbeat.item_counts == {"step": "worklogs"}

    await finish_sync_task(db_session, task.id, status="success")
    await db_session.commit()

    finished_task = await db_session.get(SyncTask, task.id)
    assert finished_task is not None
    assert finished_task.status == "success"
    assert finished_task.finished_at is not None
    assert finished_task.heartbeat_at == finished_task.finished_at


@pytest.mark.asyncio
async def test_sync_tasks_endpoint_no_side_effect_on_project_scoped_list_request(
    client, db_session
):
    project = Project(jira_key="RECAP", name="Recovery API Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    db_session.add(stale_task)
    await db_session.commit()
    await db_session.refresh(stale_task)

    response = await client.get(
        "/api/v1/traceability/sync-tasks",
        params={"project_id": project.id},
    )
    assert response.status_code == 200
    payload = response.json()
    response_task = next(item for item in payload if item["id"] == stale_task.id)

    assert response_task["status"] == "running"
    assert response_task["error_code"] is None

    task_after_list = await db_session.get(SyncTask, stale_task.id)
    assert task_after_list is not None
    assert task_after_list.status == "running"


@pytest.mark.asyncio
async def test_sync_tasks_endpoint_no_side_effect_on_detail_request(client, db_session):
    project = Project(jira_key="RECD", name="Recovery Detail Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    db_session.add(stale_task)
    await db_session.commit()
    await db_session.refresh(stale_task)

    response = await client.get(f"/api/v1/traceability/sync-tasks/{stale_task.id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["error_code"] is None

    task_after_detail = await db_session.get(SyncTask, stale_task.id)
    assert task_after_detail is not None
    assert task_after_detail.status == "running"


@pytest.mark.asyncio
async def test_sync_tasks_manual_recovery_endpoint_recovers_stale_running_task(client, db_session):
    project = Project(jira_key="RECM", name="Recovery Manual Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    db_session.add(stale_task)
    await db_session.commit()
    await db_session.refresh(stale_task)

    response = await client.post(
        "/api/v1/traceability/sync-tasks/recover-stale",
        params={"project_id": project.id},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recovered"] == 1
    assert payload["project_id"] == project.id
    assert payload["task_id"] is None
    assert payload["all"] is False

    await db_session.refresh(stale_task)
    task_after_manual_recovery = await db_session.get(SyncTask, stale_task.id)
    assert task_after_manual_recovery is not None
    assert task_after_manual_recovery.status == "failed"
    assert task_after_manual_recovery.error_code == STALE_RUNNING_ERROR_CODE


@pytest.mark.asyncio
async def test_sync_tasks_manual_recovery_endpoint_supports_global_recovery(client, db_session):
    project = Project(jira_key="RECG", name="Recovery Global Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    db_session.add(stale_task)
    await db_session.commit()
    await db_session.refresh(stale_task)

    response = await client.post(
        "/api/v1/traceability/sync-tasks/recover-stale",
        params={"all": "true"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recovered"] == 1
    assert payload["all"] is True
    assert payload["project_id"] is None
    assert payload["task_id"] is None


@pytest.mark.asyncio
async def test_sync_tasks_manual_recovery_endpoint_requires_scope_or_all(client):
    response = await client.post("/api/v1/traceability/sync-tasks/recover-stale")
    assert response.status_code == 400
    assert "Either project_id/task_id is required, or all=true" in response.text


@pytest.mark.asyncio
async def test_sync_tasks_endpoint_no_side_effect_on_forbidden_list_request(client, db_session):
    async def _override_non_admin_user():
        return _TraceabilityViewerUser()

    previous_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_non_admin_user
    try:
        project = Project(jira_key="NOFX", name="No Side Effect Project", status="active")
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)

        stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
        stale_task = SyncTask(
            project_id=project.id,
            task_type="jira_sync",
            status="running",
            started_at=stale_at,
            heartbeat_at=stale_at,
            trigger="manual",
        )
        db_session.add(stale_task)
        await db_session.commit()
        await db_session.refresh(stale_task)

        response = await client.get("/api/v1/traceability/sync-tasks")
        assert response.status_code == 403

        task_after_forbidden = await db_session.get(SyncTask, stale_task.id)
        assert task_after_forbidden is not None
        assert task_after_forbidden.status == "running"
    finally:
        if previous_override is not None:
            app.dependency_overrides[get_current_user] = previous_override
        else:
            app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_sync_tasks_manual_recovery_endpoint_requires_admin(client, db_session):
    async def _override_non_admin_user():
        return _TraceabilityViewerUser()

    previous_override = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _override_non_admin_user
    try:
        project = Project(jira_key="NOAD", name="No Admin Recovery Project", status="active")
        db_session.add(project)
        await db_session.commit()
        await db_session.refresh(project)

        stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
        stale_task = SyncTask(
            project_id=project.id,
            task_type="jira_sync",
            status="running",
            started_at=stale_at,
            heartbeat_at=stale_at,
            trigger="manual",
        )
        db_session.add(stale_task)
        await db_session.commit()
        await db_session.refresh(stale_task)

        response = await client.post(
            "/api/v1/traceability/sync-tasks/recover-stale",
            params={"project_id": project.id},
        )
        assert response.status_code == 403

        task_after_forbidden = await db_session.get(SyncTask, stale_task.id)
        assert task_after_forbidden is not None
        assert task_after_forbidden.status == "running"
    finally:
        if previous_override is not None:
            app.dependency_overrides[get_current_user] = previous_override
        else:
            app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_sync_tasks_endpoint_no_side_effect_on_not_found_task_request(client, db_session):
    project = Project(jira_key="MISS", name="Missing Task Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    stale_at = datetime.now(timezone.utc) - timedelta(hours=4)
    stale_task = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=stale_at,
        heartbeat_at=stale_at,
        trigger="manual",
    )
    db_session.add(stale_task)
    await db_session.commit()
    await db_session.refresh(stale_task)

    response = await client.get("/api/v1/traceability/sync-tasks/999999")
    assert response.status_code == 404

    task_after_not_found = await db_session.get(SyncTask, stale_task.id)
    assert task_after_not_found is not None
    assert task_after_not_found.status == "running"
