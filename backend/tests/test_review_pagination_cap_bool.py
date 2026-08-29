"""Regression tests for traceability review-queue edge cases (plan_70 follow-up).

Three independent corner cases that the happy-path suite does not exercise:

* **#3 Pagination tiebreaker** — many rows sharing one ``created_at`` must page
  deterministically. ``list_review_items`` orders by ``(created_at desc, id
  desc)`` and uses offset/limit, so without the ``id`` tiebreaker the pages
  could drop or duplicate rows. Paging through everything must yield every id
  exactly once.
* **#5 transition_notes cap** — reopen/re-resolve cycles each append a note to
  ``meta['transition_notes']``; the history is capped at
  ``_MAX_TRANSITION_NOTES`` so the metadata JSON cannot grow without bound.
* **#6 bool/None artifact ids** — ``persist_review_candidates_sync`` must reject
  ``bool`` ids (``bool`` subclasses ``int``) and ``None``, while a real ``int``
  id creates a row.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, SessionLocal
from app.models.traceability_review import (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_RESOLVED,
    TraceabilityReviewItem,
)
from app.services.traceability import review_service
from app.services.traceability.review_service import (
    list_review_items,
    persist_review_candidates_sync,
    transition_review_item,
)


# ---------------------------------------------------------------------------
# #3 Pagination tiebreaker: identical created_at must still page deterministically
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pagination_with_identical_created_at_has_no_gaps_or_dupes(db_session):
    """Insert ~120 rows that all share one ``created_at`` and page through them
    with ``limit=50``. Because ordering is ``(created_at desc, id desc)`` the
    ``id`` is the only thing distinguishing rows, so offset paging is only
    deterministic if the query keeps that tiebreaker. The union of every page
    must equal the full set of inserted ids with no duplicates and no gaps."""
    total_rows = 120
    fixed_created_at = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)

    inserted = [
        TraceabilityReviewItem(
            project_id=None,
            artifact_id=1000 + i,
            rule_id=None,
            node_id=f"node-{i}",
            status=REVIEW_STATUS_PENDING,
            priority="normal",
            created_at=fixed_created_at,
            updated_at=fixed_created_at,
        )
        for i in range(total_rows)
    ]
    db_session.add_all(inserted)
    await db_session.commit()

    # Read paginated results from a fresh session to avoid WAL snapshot
    # staleness against the just-committed writes.
    async with AsyncSessionLocal() as s:
        all_ids = set((await s.execute(select(TraceabilityReviewItem.id))).scalars().all())
        assert len(all_ids) == total_rows

        collected: list[int] = []
        limit = 50
        for page in range(3):  # 50 + 50 + 20 = 120
            total, items = await list_review_items(s, skip=page * limit, limit=limit)
            assert total == total_rows
            collected.extend(item.id for item in items)

    # No duplicates across pages, and the union covers exactly every inserted id.
    assert len(collected) == total_rows
    assert len(set(collected)) == total_rows  # no duplicates
    assert set(collected) == all_ids  # no gaps

    # The first page must also be globally sorted by id desc (the tiebreaker),
    # confirming the order is stable rather than incidental.
    expected_first_page = sorted(all_ids, reverse=True)[:limit]
    assert collected[:limit] == expected_first_page


# ---------------------------------------------------------------------------
# #5 transition_notes cap: repeated legal transitions cannot grow meta unbounded
# ---------------------------------------------------------------------------
def test_transition_notes_are_capped_across_reopen_cycles():
    """Alternate the only legal note-bearing cycle (pending<->resolved, where
    resolved->pending is a privileged reopen) 120 times, attaching a note each
    time. The retained ``transition_notes`` history must be capped at
    ``_MAX_TRANSITION_NOTES`` and keep the most recent entries."""
    item = TraceabilityReviewItem(
        artifact_id=1,
        node_id="n",
        status=REVIEW_STATUS_PENDING,
        priority="normal",
    )

    cycles = 120
    for i in range(cycles):
        # Status graph: pending -> resolved is allowed; resolved -> pending is a
        # reopen. Both legs carry a note, so every iteration appends two entries.
        transition_review_item(
            item,
            target_status=REVIEW_STATUS_RESOLVED,
            actor_id=7,
            note=f"resolve-{i}",
        )
        transition_review_item(
            item,
            target_status=REVIEW_STATUS_PENDING,
            actor_id=7,
            note=f"reopen-{i}",
        )

    notes = item.meta["transition_notes"]
    # We appended 240 notes total but the history must be capped.
    assert len(notes) <= review_service._MAX_TRANSITION_NOTES
    assert len(notes) == review_service._MAX_TRANSITION_NOTES  # full cap reached

    # The cap keeps the MOST RECENT entries; the final note is the last reopen.
    assert notes[-1]["note"] == f"reopen-{cycles - 1}"
    assert notes[-1]["from"] == REVIEW_STATUS_RESOLVED
    assert notes[-1]["to"] == REVIEW_STATUS_PENDING
    # The oldest retained entry is newer than the very first note we appended.
    assert notes[0]["note"] != "resolve-0"
    # Final in-memory status is back to pending after the last reopen.
    assert item.status == REVIEW_STATUS_PENDING


# ---------------------------------------------------------------------------
# #6 bool / None artifact ids must not create rows; a real int id must
# ---------------------------------------------------------------------------
def test_persist_rejects_bool_and_none_artifact_ids():
    """``bool`` is a subclass of ``int``; ``persist_review_candidates_sync`` must
    reject ``True``/``False`` (so they cannot be coerced into artifact_id 0/1)
    and ``None``, while a genuine ``int`` id creates exactly one row."""
    invalid_candidates = [
        {"artifact_id": True, "node_id": "n-true", "priority": "normal"},
        {"artifact_id": False, "node_id": "n-false", "priority": "normal"},
        {"artifact_id": None, "node_id": "n-none", "priority": "normal"},
    ]
    valid_artifact_id = 555_001
    valid_candidate = {
        "artifact_id": valid_artifact_id,
        "node_id": "n-valid",
        "priority": "high",
        "reason": "real id",
    }

    with SessionLocal() as db:
        summary = persist_review_candidates_sync(
            db,
            rule_id=4242,
            execution_id=None,
            candidates=[*invalid_candidates, valid_candidate],
        )
        db.commit()

    # Only the single valid int id is persisted.
    assert summary == {"created": 1, "updated": 0}

    # Read back from a fresh sync session (new connection post-commit) to assert
    # the durable row count, mirroring the sync-engine tests in the suite.
    with SessionLocal() as db:
        rows = db.query(TraceabilityReviewItem).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.artifact_id == valid_artifact_id
        assert row.node_id == "n-valid"
        assert row.status == REVIEW_STATUS_PENDING

        # No row exists for the coerced bool ids (True->1, False->0) or None.
        coerced = (
            db.query(TraceabilityReviewItem)
            .filter(TraceabilityReviewItem.artifact_id.in_([0, 1]))
            .all()
        )
        assert coerced == []


def test_persist_accepts_zero_as_a_genuine_int():
    """Positive counterpart to the bool rejection: ``0`` is a genuine ``int``
    (not a ``bool``), so it is accepted and DOES create a row. This pins the
    intended distinction — ``False == 0`` but is rejected as a bool, whereas the
    integer ``0`` is a valid id and is persisted."""
    with SessionLocal() as db:
        summary = persist_review_candidates_sync(
            db,
            rule_id=4242,
            execution_id=None,
            candidates=[{"artifact_id": 0, "node_id": "n-zero", "priority": "normal"}],
        )
        db.commit()

    assert summary == {"created": 1, "updated": 0}
    with SessionLocal() as db:
        rows = db.query(TraceabilityReviewItem).all()
        assert len(rows) == 1
        assert rows[0].artifact_id == 0
        assert type(rows[0].artifact_id) is int
