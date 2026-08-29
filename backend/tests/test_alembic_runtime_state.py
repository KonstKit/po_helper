from __future__ import annotations

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
async def test_alembic_runtime_state_raises_when_table_missing(monkeypatch: pytest.MonkeyPatch):
    connection = _FakeConnection(scalar_results=[None])
    monkeypatch.setattr(app_main, "engine", _FakeEngine("postgresql", connection))

    with pytest.raises(RuntimeError, match="alembic_version is missing"):
        await app_main._ensure_postgres_alembic_runtime_state()


@pytest.mark.asyncio
async def test_alembic_runtime_state_widens_short_version_column(monkeypatch: pytest.MonkeyPatch):
    connection = _FakeConnection(
        scalar_results=[
            "public",  # schema
            32,  # character_maximum_length for alembic_version.version_num
            1,  # row count
            "031_add_running_sync_task_unique_lease",  # current revision
        ]
    )
    monkeypatch.setattr(app_main, "engine", _FakeEngine("postgresql", connection))

    await app_main._ensure_postgres_alembic_runtime_state()

    assert any(
        'ALTER TABLE "public"."alembic_version" ALTER COLUMN version_num TYPE VARCHAR(255)' in sql
        for sql in connection.executed_sql
    )


@pytest.mark.asyncio
async def test_alembic_runtime_state_requires_single_version_row(monkeypatch: pytest.MonkeyPatch):
    connection = _FakeConnection(
        scalar_results=[
            "public",  # schema
            255,  # character_maximum_length
            0,  # row count
        ]
    )
    monkeypatch.setattr(app_main, "engine", _FakeEngine("postgresql", connection))

    with pytest.raises(RuntimeError, match="must contain exactly one row"):
        await app_main._ensure_postgres_alembic_runtime_state()


@pytest.mark.asyncio
async def test_alembic_runtime_state_is_noop_for_sqlite(monkeypatch: pytest.MonkeyPatch):
    connection = _FakeConnection(scalar_results=[])
    monkeypatch.setattr(app_main, "engine", _FakeEngine("sqlite", connection))

    await app_main._ensure_postgres_alembic_runtime_state()
    assert connection.executed_sql == []
