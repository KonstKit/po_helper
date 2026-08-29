"""Regression tests for the traceability review queue: concurrent-claim
serialization (case #2) and release-claim RBAC (case #4).

Two behaviors are pinned here:

* **Re-claim rejection** (deterministic stand-in for the concurrent-claim
  race): the endpoint row-locks with ``for_update`` so two simultaneous claims
  serialize; the second observes the post-claim status and is rejected by the
  status graph (``claimed -> claimed`` is not an allowed transition) with 409.
* **Release-claim RBAC**: releasing a claim back to ``pending`` requires
  administrator rights only when the claim belongs to ANOTHER operator. An
  operator may release their OWN claim without elevation.

The reopen-terminal-403 case is already covered by
``test_traceability_review.py`` and is intentionally not duplicated here.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.traceability_review import (
    REVIEW_STATUS_CLAIMED,
    REVIEW_STATUS_PENDING,
    TraceabilityReviewItem,
)


class _Manager:
    """A traceability manager who is NOT an administrator/superuser."""

    id = 4242
    email = "m@x.io"
    is_active = True
    is_superuser = False

    def has_permission(self, p: str) -> bool:
        return p in {"traceability:view", "traceability:manage"}

    def has_role(self, r: str) -> bool:
        return False


@pytest_asyncio.fixture
async def pending_item(db_session):
    """Seed a pending, project-less review item (project_id=None skips the
    per-project access check in the endpoint)."""
    item = TraceabilityReviewItem(
        project_id=None,
        artifact_id=2001,
        rule_id=None,
        node_id="review-1",
        status=REVIEW_STATUS_PENDING,
        priority="normal",
        reason="please review",
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Case #2: concurrent-claim serialization (deterministic re-claim stand-in)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reclaim_rejected_after_claim(client, pending_item, auth_headers):
    """First claim succeeds (pending -> claimed); a second claim is rejected by
    the status graph (claimed -> claimed is illegal) with 409. This is the
    deterministic stand-in for the concurrent-claim race the endpoint guards
    against with a ``for_update`` row lock."""
    first = await client.post(
        f"/api/v1/traceability/review-items/{pending_item.id}/claim",
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["status"] == REVIEW_STATUS_CLAIMED

    second = await client.post(
        f"/api/v1/traceability/review-items/{pending_item.id}/claim",
        headers=auth_headers,
    )
    assert second.status_code == 409

    # The item remains claimed; the rejected re-claim did not change state.
    # Read from a fresh session to avoid WAL snapshot staleness.
    async with AsyncSessionLocal() as s:
        status = (
            await s.execute(
                select(TraceabilityReviewItem.status).where(
                    TraceabilityReviewItem.id == pending_item.id
                )
            )
        ).scalar_one()
        assert status == REVIEW_STATUS_CLAIMED


# ---------------------------------------------------------------------------
# Case #4: release-claim RBAC
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_non_admin_manager_cannot_release_others_claim(db_session, client, auth_headers):
    """A non-admin manager releasing ANOTHER operator's claim must get 403
    (releasing someone else's claim requires administrator rights)."""
    from app.api.deps import get_current_user
    from app.main import app

    # Item claimed by a DIFFERENT operator (id 999).
    item = TraceabilityReviewItem(
        project_id=None,
        artifact_id=2002,
        node_id="review-1",
        status=REVIEW_STATUS_CLAIMED,
        priority="normal",
        assigned_to_id=999,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: _Manager()
    try:
        resp = await client.post(
            f"/api/v1/traceability/review-items/{item.id}/reopen",
            headers=auth_headers,
        )
        assert resp.status_code == 403
    finally:
        if original is not None:
            app.dependency_overrides[get_current_user] = original
        else:
            app.dependency_overrides.pop(get_current_user, None)

    # The claim is untouched: still claimed, still assigned to the other operator.
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(
                    TraceabilityReviewItem.status,
                    TraceabilityReviewItem.assigned_to_id,
                ).where(TraceabilityReviewItem.id == item.id)
            )
        ).one()
        assert row.status == REVIEW_STATUS_CLAIMED
        assert row.assigned_to_id == 999


@pytest.mark.asyncio
async def test_non_admin_manager_can_release_own_claim(db_session, client, auth_headers):
    """A non-admin manager releasing their OWN claim is permitted (200), and the
    item returns to pending with the assignee cleared."""
    from app.api.deps import get_current_user
    from app.main import app

    # Item claimed by the manager themselves (id 4242).
    item = TraceabilityReviewItem(
        project_id=None,
        artifact_id=2003,
        node_id="review-1",
        status=REVIEW_STATUS_CLAIMED,
        priority="normal",
        assigned_to_id=_Manager.id,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: _Manager()
    try:
        resp = await client.post(
            f"/api/v1/traceability/review-items/{item.id}/reopen",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == REVIEW_STATUS_PENDING
    finally:
        if original is not None:
            app.dependency_overrides[get_current_user] = original
        else:
            app.dependency_overrides.pop(get_current_user, None)

    # Released back to pending and unassigned; read from a fresh session.
    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(
                select(
                    TraceabilityReviewItem.status,
                    TraceabilityReviewItem.assigned_to_id,
                ).where(TraceabilityReviewItem.id == item.id)
            )
        ).one()
        assert row.status == REVIEW_STATUS_PENDING
        assert row.assigned_to_id is None
