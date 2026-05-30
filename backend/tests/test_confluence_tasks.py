from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.confluence import ConfluencePage
from app.tasks.confluence_tasks import (
    _async_sync_space,
    _process_page,
    _start_confluence_tracking,
    confluence_service,
)


def _page_payload(page_id: str, version: int) -> dict[str, object]:
    return {
        "id": page_id,
        "title": f"Page {page_id}",
        "type": "page",
        "space": {"key": "DOC"},
        "_links": {"webui": f"/spaces/DOC/pages/{page_id}"},
        "version": {"number": version},
        "history": {},
        "metadata": {"labels": []},
        "body": {"storage": {"value": "<p>content</p>"}},
    }


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_process_page_sets_non_null_updated_at_with_missing_updated_dates(db_session):
    confluence_service.base_url = "https://confluence.example.com"

    created, _page_row = await _process_page(db_session, _page_payload("1001", 1))
    await db_session.commit()
    assert created is True

    stored = (
        await db_session.execute(
            select(ConfluencePage).where(ConfluencePage.confluence_id == "1001")
        )
    ).scalar_one_or_none()
    assert stored is not None
    assert stored.updated is not None
    assert stored.updated_at is not None

    updated, _page_row = await _process_page(db_session, _page_payload("1001", 2))
    await db_session.commit()
    assert updated is False

    stored_after_update = (
        await db_session.execute(
            select(ConfluencePage).where(ConfluencePage.confluence_id == "1001")
        )
    ).scalar_one_or_none()
    assert stored_after_update is not None
    assert stored_after_update.version == 2
    assert stored_after_update.updated is not None
    assert stored_after_update.updated_at is not None


@pytest.mark.asyncio
async def test_inserting_page_without_updated_at_is_populated_by_server_default(db_session):
    """Regression: a ConfluencePage inserted WITHOUT ``updated_at`` must be
    auto-populated, not rejected.

    The API sync paths (``endpoints/confluence.py`` single + bulk upsert) build
    ``ConfluencePage`` without setting ``updated_at``. The column is NOT NULL and
    its only timestamp hook used to be ``onupdate`` (which fires on UPDATE only),
    so the ORM emitted NULL on INSERT and every new-page insert from those paths
    failed with a ``NotNullViolation``. ``updated_at`` now carries
    ``server_default=func.now()`` (mirroring ``created_at``), so an insert that
    omits it is filled by the database instead of failing.
    """
    page = ConfluencePage(
        confluence_id="server-default-1",
        space_key="DOC",
        title="No updated_at provided",
        page_type="page",
        url="https://confluence.example.com/server-default-1",
        version=1,
        created=datetime.now(timezone.utc),
        updated=datetime.now(timezone.utc),
        labels=None,
        html="<p>content</p>",
        # updated_at intentionally NOT set — mirrors the API sync upsert paths.
    )
    db_session.add(page)
    await db_session.commit()  # would raise NotNullViolation before the fix

    stored = (
        await db_session.execute(
            select(ConfluencePage).where(ConfluencePage.confluence_id == "server-default-1")
        )
    ).scalar_one_or_none()
    assert stored is not None
    assert stored.created_at is not None  # server_default (pre-existing)
    assert stored.updated_at is not None  # server_default (the fix)


@pytest.mark.asyncio
async def test_async_sync_space_fetches_remote_pages_before_opening_db_session(monkeypatch):
    db_session_open = False
    observed_during_fetch: list[bool] = []

    class DummyTask:
        total_pages = 0
        processed_pages = 0
        created_count = 0
        updated_count = 0

        def update_progress(self, message: str, percent: int | None = None) -> None:
            return None

    class FakeSession:
        async def __aenter__(self):
            nonlocal db_session_open
            db_session_open = True
            return self

        async def __aexit__(self, exc_type, exc, tb):
            nonlocal db_session_open
            db_session_open = False

        async def commit(self) -> None:
            return None

    monkeypatch.setattr(
        "app.tasks.confluence_tasks.AsyncSessionLocal",
        lambda: FakeSession(),
    )
    monkeypatch.setattr(
        "app.tasks.confluence_tasks._start_confluence_tracking",
        lambda *args, **kwargs: _async_return((None, None, "run-key", True)),
    )
    monkeypatch.setattr(
        "app.tasks.confluence_tasks.confluence_service.list_pages",
        lambda **kwargs: [{"id": "1001"}] if kwargs.get("start", 0) == 0 else [],
    )

    def fake_get_page_by_id(page_id: str, expand: str | None = None):
        observed_during_fetch.append(db_session_open)
        return _page_payload(page_id, 1)

    monkeypatch.setattr(
        "app.tasks.confluence_tasks.confluence_service.get_page_by_id",
        fake_get_page_by_id,
    )

    async def fake_process_page(db, page_data):
        # _process_page returns (created, page_row); the caller unpacks it and
        # feeds page_row into the artifact-sync service.
        return True, SimpleNamespace(id=1, confluence_id=page_data.get("id"))

    async def fake_finalize_tracking(**_kwargs):
        return None

    class _FakeArtifactSync:
        async def sync_confluence_page_artifacts(self, db, page_row, **kwargs):
            return SimpleNamespace(created=0, updated=0, project_ids=set())

    monkeypatch.setattr("app.tasks.confluence_tasks._process_page", fake_process_page)
    monkeypatch.setattr(
        "app.tasks.confluence_tasks.get_traceability_artifact_sync_service",
        lambda: _FakeArtifactSync(),
    )
    monkeypatch.setattr(
        "app.tasks.confluence_tasks._finalize_confluence_tracking",
        fake_finalize_tracking,
    )

    result = await _async_sync_space(DummyTask(), "DOC", None, True)

    assert result == {
        "synced": 1,
        "created": 1,
        "updated": 0,
        "artifacts_created": 0,
        "artifacts_updated": 0,
        "projects_affected": [],
    }
    assert observed_during_fetch == [False]


@pytest.mark.asyncio
async def test_async_sync_space_fails_closed_when_tracking_init_fails(monkeypatch):
    class DummyTask:
        total_pages = 0
        processed_pages = 0
        created_count = 0
        updated_count = 0

        def update_progress(self, message: str, percent: int | None = None) -> None:
            return None

    async def _raise_tracking(*_args, **_kwargs):
        raise RuntimeError("tracking unavailable")

    monkeypatch.setattr("app.tasks.confluence_tasks._start_confluence_tracking", _raise_tracking)

    with pytest.raises(RuntimeError, match="tracking initialization failed"):
        await _async_sync_space(DummyTask(), "DOC", None, True)


@pytest.mark.asyncio
async def test_async_sync_space_short_circuits_duplicate_run(monkeypatch):
    class DummyTask:
        total_pages = 0
        processed_pages = 0
        created_count = 0
        updated_count = 0

        def update_progress(self, message: str, percent: int | None = None) -> None:
            return None

    async def _duplicate_tracking(*_args, **_kwargs):
        return 1, 42, '{"full_sync":true,"query":null,"space_key":"DOC"}', False

    monkeypatch.setattr(
        "app.tasks.confluence_tasks._start_confluence_tracking",
        _duplicate_tracking,
    )
    monkeypatch.setattr(
        "app.tasks.confluence_tasks.confluence_service.list_pages",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("list_pages must not be called")),
    )

    result = await _async_sync_space(DummyTask(), "DOC", None, True)
    assert result["duplicate"] is True
    assert result["skipped"] is True


@pytest.mark.asyncio
async def test_start_tracking_duplicate_does_not_touch_existing_heartbeat(monkeypatch):
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def execute(self, *_args, **_kwargs):
            return None

    @asynccontextmanager
    async def _fake_tx(_db):
        yield

    now = datetime.now(timezone.utc)
    existing = SimpleNamespace(id=99, heartbeat_at=now, started_at=now)
    calls: dict[str, int] = {"touch": 0}

    async def _touch(*_args, **_kwargs):
        calls["touch"] += 1

    monkeypatch.setattr("app.tasks.confluence_tasks.AsyncSessionLocal", lambda: _FakeSession())
    monkeypatch.setattr("app.tasks.confluence_tasks.transactional_session", _fake_tx)

    async def _get_source(*_args, **_kwargs):
        return SimpleNamespace(id=7)

    async def _find_running(*_args, **_kwargs):
        return existing

    monkeypatch.setattr("app.tasks.confluence_tasks.get_or_create_source", _get_source)
    monkeypatch.setattr("app.tasks.confluence_tasks.supports_for_update", lambda _db: False)
    monkeypatch.setattr("app.tasks.confluence_tasks._find_running_confluence_task", _find_running)
    monkeypatch.setattr("app.tasks.confluence_tasks.touch_sync_task_heartbeat", _touch)

    source_id, task_id, _run_key, created_new = await _start_confluence_tracking(
        space_key="DOC",
        query=None,
        full_sync=True,
        trigger="manual",
    )

    assert source_id == 7
    assert task_id == 99
    assert created_new is False
    assert calls["touch"] == 0
