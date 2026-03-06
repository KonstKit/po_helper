from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.traceability import SyncTask
from app.services.jira_service import jira_service
from app.services.sync.project_sync_orchestrator import (
    LEASE_ACQUIRE_ERROR_CODE,
    LEASE_LOST_ERROR_CODE,
    ProjectSyncOrchestrator,
)


@pytest.mark.asyncio
async def test_sync_project_aborts_when_reserved_lease_is_not_running(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    project = Project(name="Lease Project", jira_key="LEASE", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    now = datetime.now(timezone.utc)
    stale_lease = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="failed",
        started_at=now - timedelta(minutes=20),
        heartbeat_at=now - timedelta(minutes=15),
        finished_at=now - timedelta(minutes=10),
        trigger="manual",
        error_code="dispatch_failed",
    )
    db_session.add(stale_lease)
    await db_session.commit()
    await db_session.refresh(stale_lease)

    async def _unexpected_issue_fetch(_project_key: str):
        raise AssertionError("Worker must stop before Jira API fetch when reserved lease is lost")

    monkeypatch.setattr(jira_service, "async_get_project_issues", _unexpected_issue_fetch)

    orchestrator = ProjectSyncOrchestrator()
    result = await orchestrator.sync_project(
        "LEASE",
        project.id,
        trigger="manual",
        sync_task_id=stale_lease.id,
    )

    assert result.success is False
    assert result.failure_reason == LEASE_LOST_ERROR_CODE
    assert result.errors
    assert result.errors[0][0] == "lease"
    assert "no longer valid" in result.errors[0][1]

    stale_lease_after = await db_session.get(SyncTask, stale_lease.id)
    assert stale_lease_after is not None
    assert stale_lease_after.status == "failed"
    assert stale_lease_after.error_code == "dispatch_failed"

    tasks = (
        await db_session.execute(
            select(SyncTask).where(
                SyncTask.project_id == project.id,
                SyncTask.task_type == "jira_sync",
            )
        )
    ).scalars().all()
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_sync_project_aborts_when_unreserved_lease_acquire_fails(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
):
    project = Project(name="Lease Acquire Project", jira_key="LEASE2", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    now = datetime.now(timezone.utc)
    running_lease = SyncTask(
        project_id=project.id,
        task_type="jira_sync",
        status="running",
        started_at=now - timedelta(minutes=1),
        heartbeat_at=now,
        trigger="schedule",
    )
    db_session.add(running_lease)
    await db_session.commit()
    await db_session.refresh(running_lease)

    async def _unexpected_issue_fetch(_project_key: str):
        raise AssertionError("Worker must stop before Jira API fetch when lease acquire fails")

    monkeypatch.setattr(jira_service, "async_get_project_issues", _unexpected_issue_fetch)

    orchestrator = ProjectSyncOrchestrator()
    result = await orchestrator.sync_project(
        "LEASE2",
        project.id,
        trigger="manual",
    )

    assert result.success is False
    assert result.failure_reason == LEASE_ACQUIRE_ERROR_CODE
    assert result.errors
    assert result.errors[0][0] == "lease"
    assert "Failed to acquire Jira sync lease" in result.errors[0][1]

    running_lease_after = await db_session.get(SyncTask, running_lease.id)
    assert running_lease_after is not None
    assert running_lease_after.status == "running"

    tasks = (
        await db_session.execute(
            select(SyncTask).where(
                SyncTask.project_id == project.id,
                SyncTask.task_type == "jira_sync",
            )
        )
    ).scalars().all()
    assert len(tasks) == 1
