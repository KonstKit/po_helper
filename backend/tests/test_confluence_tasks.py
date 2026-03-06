from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.confluence import ConfluencePage
from app.tasks.confluence_tasks import _async_sync_space, _process_page, confluence_service


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


@pytest.mark.asyncio
async def test_process_page_sets_non_null_updated_at_with_missing_updated_dates(db_session):
    confluence_service.base_url = "https://confluence.example.com"

    created = await _process_page(db_session, _page_payload("1001", 1))
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

    updated = await _process_page(db_session, _page_payload("1001", 2))
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

    def fake_session_factory():
        return FakeSession()

    monkeypatch.setattr(
        "app.tasks.confluence_tasks.AsyncSessionLocal",
        fake_session_factory,
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
        return True

    monkeypatch.setattr("app.tasks.confluence_tasks._process_page", fake_process_page)

    result = await _async_sync_space(DummyTask(), "DOC", None, True)

    assert result == {"synced": 1, "created": 1, "updated": 0}
    assert observed_during_fetch == [False]
