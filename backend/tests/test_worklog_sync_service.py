from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, Task, WorkLog
from app.services.sync.worklog_sync_service import WorklogSyncService


class _FakeJiraService:
    def __init__(self, worklogs_by_issue: dict[str, list[dict[str, object]]]) -> None:
        self.worklogs_by_issue = worklogs_by_issue

    async def async_get_issue_worklogs(self, issue_key: str) -> list[dict[str, object]]:
        return list(self.worklogs_by_issue.get(issue_key, []))


def _issue(issue_key: str, updated: str) -> dict[str, object]:
    return {"key": issue_key, "fields": {"updated": updated}}


def _worklog(worklog_id: str) -> dict[str, object]:
    return {
        "id": worklog_id,
        "author": {"displayName": "Sync Bot", "emailAddress": "sync@example.com"},
        "comment": "imported",
        "timeSpentSeconds": 600,
        "started": "2026-03-01T10:00:00.000+0000",
        "created": "2026-03-01T10:00:00.000+0000",
        "updated": "2026-03-01T10:00:00.000+0000",
    }


@pytest.mark.asyncio
async def test_sync_worklogs_no_nested_transaction_error_with_active_session(db_session):
    project = Project(jira_key="WLTX", name="Worklog Tx Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    task = Task(
        jira_id="jira-wltx-1",
        key="WLTX-1",
        summary="Worklog Task",
        status="In Progress",
        project_id=project.id,
    )
    db_session.add(task)
    await db_session.commit()

    # Keep session transaction active before sync to emulate orchestrator flow.
    await db_session.execute(select(Task.id))

    service = WorklogSyncService(
        _FakeJiraService({"WLTX-1": [_worklog("wl-1")]})  # type: ignore[arg-type]
    )
    result = await service.sync_worklogs(
        project_key=project.jira_key,
        project_id=project.id,
        issues=[_issue("WLTX-1", "2026-03-02T00:00:00.000+0000")],
        db=db_session,
    )

    assert result.errors == []
    assert result.total_issues_processed == 1
    assert result.total_worklogs_imported == 1

    stored = (
        await db_session.execute(select(WorkLog).where(WorkLog.jira_id == "wl-1"))
    ).scalar_one_or_none()
    assert stored is not None
    assert stored.task_id == task.id


@pytest.mark.asyncio
async def test_sync_worklogs_rolls_back_failed_issue_and_continues(db_session):
    project = Project(jira_key="WLRB", name="Worklog Rollback Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    task_one = Task(
        jira_id="jira-wlrb-1",
        key="WLRB-1",
        summary="Issue One",
        status="In Progress",
        project_id=project.id,
    )
    task_two = Task(
        jira_id="jira-wlrb-2",
        key="WLRB-2",
        summary="Issue Two",
        status="In Progress",
        project_id=project.id,
    )
    db_session.add_all([task_one, task_two])
    await db_session.commit()

    service = WorklogSyncService(
        _FakeJiraService(
            {
                "WLRB-1": [_worklog("wl-rollback"), _worklog("wl-boom")],
                "WLRB-2": [_worklog("wl-success")],
            }
        )  # type: ignore[arg-type]
    )

    original_upsert = service._upsert_worklog

    async def _flaky_upsert(worklog: dict[str, object], task_id: int, db) -> None:
        if worklog.get("id") == "wl-boom":
            raise RuntimeError("boom")
        await original_upsert(worklog, task_id, db)

    service._upsert_worklog = _flaky_upsert  # type: ignore[method-assign]

    result = await service.sync_worklogs(
        project_key=project.jira_key,
        project_id=project.id,
        issues=[
            _issue("WLRB-1", "2026-03-02T00:00:00.000+0000"),
            _issue("WLRB-2", "2026-03-01T00:00:00.000+0000"),
        ],
        db=db_session,
    )

    assert result.total_issues_processed == 2
    assert result.total_worklogs_imported == 1
    assert len(result.errors) == 1
    assert result.errors[0][0] == "WLRB-1"

    stored_ids = [
        row[0]
        for row in (
            await db_session.execute(select(WorkLog.jira_id).order_by(WorkLog.jira_id))
        ).all()
    ]
    assert stored_ids == ["wl-success"]
