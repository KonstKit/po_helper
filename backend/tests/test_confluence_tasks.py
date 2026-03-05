from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.confluence import ConfluencePage
from app.tasks.confluence_tasks import _process_page, confluence_service


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
