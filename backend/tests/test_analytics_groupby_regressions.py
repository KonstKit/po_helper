from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.dialects import postgresql

from app.services.analytics.capacity_service import get_sprint_capacity
from app.services.analytics.quality_service import get_sprint_quality


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeQualitySession:
    def __init__(self):
        self.statements = []
        self._calls = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        self._calls += 1
        if self._calls == 1:
            return _FakeMappingsResult(
                [
                    {
                        "total": 3,
                        "done": 1,
                        "blockers": 0,
                    }
                ]
            )
        return _FakeMappingsResult(
            [
                {
                    "priority": "High",
                    "bug_count": 2,
                }
            ]
        )


class _FakeCapacitySession:
    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _FakeMappingsResult(
            [
                {
                    "assignee": "unassigned",
                    "email": None,
                    "planned_hours": 8.0,
                }
            ]
        )


@pytest.mark.asyncio
async def test_sprint_quality_uses_same_coalesce_bind_for_select_and_group_by():
    fake_db = _FakeQualitySession()

    payload = await get_sprint_quality(db=fake_db, sprint_id=101)

    assert payload["total_tasks"] == 3
    assert len(fake_db.statements) == 2
    compiled = fake_db.statements[1].compile(dialect=postgresql.dialect())
    coalesce_params = [key for key in compiled.params if key.startswith("coalesce_")]

    # Regression guard: old query produced coalesce_1/coalesce_2 and failed on PostgreSQL GROUP BY.
    assert coalesce_params == ["coalesce_1"]


@pytest.mark.asyncio
async def test_sprint_capacity_uses_same_coalesce_bind_for_select_and_group_by(monkeypatch):
    fake_db = _FakeCapacitySession()

    async def _fake_fetch_sprint_meta(_db, _sprint_id):
        return {
            "project_id": 1,
            "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "end_date": datetime(2026, 1, 15, tzinfo=timezone.utc),
        }

    monkeypatch.setattr(
        "app.services.analytics.capacity_service.fetch_sprint_meta",
        _fake_fetch_sprint_meta,
    )

    payload = await get_sprint_capacity(db=fake_db, sprint_id=202)

    assert payload["sprint_id"] == 202
    assert len(fake_db.statements) == 1
    compiled = fake_db.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)

    # Regression guard: assignee coalesce bind must be shared between SELECT and GROUP BY.
    assert "coalesce(tasks.assignee_email, tasks.assignee_name, %(coalesce_1)s) AS assignee" in sql
    assert (
        "GROUP BY coalesce(tasks.assignee_email, tasks.assignee_name, %(coalesce_1)s), "
        "tasks.assignee_email"
    ) in sql
