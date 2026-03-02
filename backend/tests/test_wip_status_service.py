from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.models import Project, Sprint, Task
from app.services.analytics.wip_status_service import get_sprint_wip_status


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeAsyncSession:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeMappingsResult(self.rows)


@pytest.mark.asyncio
async def test_wip_status_uses_same_coalesce_bind_for_select_and_group_by():
    fake_db = _FakeAsyncSession(rows=[{"assignee": "alice@example.com", "active_count": 2}])

    await get_sprint_wip_status(db=fake_db, sprint_id=101)

    assert len(fake_db.statements) == 1
    compiled = fake_db.statements[0].compile(dialect=postgresql.dialect())
    coalesce_params = [key for key in compiled.params if key.startswith("coalesce_")]

    # Regression guard: old query produced coalesce_1/coalesce_2 and failed on PostgreSQL GROUP BY.
    assert coalesce_params == ["coalesce_1"]


@pytest.mark.asyncio
async def test_wip_status_groups_active_tasks_by_coalesced_assignee(db_session, monkeypatch):
    project = Project(jira_key="WIP", name="WIP Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    now = datetime.now(timezone.utc)
    sprint = Sprint(
        jira_id="WIP-SPR-1",
        name="Sprint WIP",
        state="active",
        project_id=project.id,
        start_date=now - timedelta(days=5),
        end_date=now + timedelta(days=5),
    )
    db_session.add(sprint)
    await db_session.commit()
    await db_session.refresh(sprint)

    db_session.add_all(
        [
            Task(
                jira_id="WIP-1",
                key="WIP-1",
                summary="Task 1",
                status="In Progress",
                project_id=project.id,
                sprint_id=sprint.id,
                assignee_email="alice@example.com",
            ),
            Task(
                jira_id="WIP-2",
                key="WIP-2",
                summary="Task 2",
                status="To Do",
                project_id=project.id,
                sprint_id=sprint.id,
                assignee_email="alice@example.com",
            ),
            Task(
                jira_id="WIP-3",
                key="WIP-3",
                summary="Task 3",
                status="In Progress",
                project_id=project.id,
                sprint_id=sprint.id,
                assignee_name="Bob",
            ),
            Task(
                jira_id="WIP-4",
                key="WIP-4",
                summary="Task 4",
                status="In Progress",
                project_id=project.id,
                sprint_id=sprint.id,
            ),
            Task(
                jira_id="WIP-5",
                key="WIP-5",
                summary="Task 5",
                status="Done",
                project_id=project.id,
                sprint_id=sprint.id,
                assignee_email="alice@example.com",
            ),
        ]
    )
    await db_session.commit()

    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "WIP_LIMIT_PER_ASSIGNEE", 2)
    monkeypatch.setattr(app_settings, "WIP_LIMIT_OVERRIDES", {"alice@example.com": 1})

    payload = await get_sprint_wip_status(db=db_session, sprint_id=sprint.id)

    assert payload["total_active"] == 4
    assert payload["limit_default"] == 2
    assert [item["assignee"] for item in payload["assignees"]] == [
        "alice@example.com",
        "Bob",
        "unassigned",
    ]

    alice = payload["assignees"][0]
    assert alice["active_tasks"] == 2
    assert alice["limit"] == 1
    assert alice["wip_exceeded"] is True
