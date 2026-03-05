from __future__ import annotations

import logging

import pytest

from app import main as app_main


class _FakeConnection:
    def __init__(self, scalar_results: list[object]) -> None:
        self._scalar_results = list(scalar_results)
        self.executed_sql: list[str] = []

    async def scalar(self, _statement, *_args, **_kwargs):
        if not self._scalar_results:
            raise AssertionError("Unexpected scalar() call")
        return self._scalar_results.pop(0)

    async def execute(self, statement):
        sql = getattr(statement, "text", str(statement))
        self.executed_sql.append(" ".join(str(sql).split()))


class _FakeBeginContext:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeUrl:
    def __init__(self, backend_name: str) -> None:
        self._backend_name = backend_name

    def get_backend_name(self) -> str:
        return self._backend_name


class _FakeEngine:
    def __init__(self, backend_name: str, connection: _FakeConnection) -> None:
        self.url = _FakeUrl(backend_name)
        self._connection = connection

    def begin(self) -> _FakeBeginContext:
        return _FakeBeginContext(self._connection)


@pytest.mark.asyncio
async def test_postgres_startup_reconcile_repairs_missing_sync_tasks_heartbeat_and_index(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    connection = _FakeConnection(
        scalar_results=[
            False,  # alembic_version table missing
            "public",  # sync_tasks schema
            False,  # heartbeat_at missing
            False,  # ix_sync_tasks_status_heartbeat missing
        ]
    )
    monkeypatch.setattr(app_main, "engine", _FakeEngine("postgresql", connection))
    caplog.set_level(logging.WARNING)

    await app_main._ensure_postgres_sync_tasks_schema()

    assert any(
        "ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ" in sql
        for sql in connection.executed_sql
    )
    assert any(
        "CREATE INDEX IF NOT EXISTS ix_sync_tasks_status_heartbeat" in sql
        for sql in connection.executed_sql
    )
    assert "alembic_version table is missing" in caplog.text


@pytest.mark.asyncio
async def test_postgres_startup_reconcile_is_noop_when_schema_is_already_current(
    monkeypatch: pytest.MonkeyPatch,
):
    connection = _FakeConnection(
        scalar_results=[
            True,  # alembic_version table exists
            "public",  # sync_tasks schema
            True,  # heartbeat_at exists
            True,  # ix_sync_tasks_status_heartbeat exists
        ]
    )
    monkeypatch.setattr(app_main, "engine", _FakeEngine("postgresql", connection))

    await app_main._ensure_postgres_sync_tasks_schema()

    assert connection.executed_sql == []
