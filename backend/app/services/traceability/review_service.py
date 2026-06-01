"""Service layer for the traceability manual-review queue (plan_70).

Two execution contexts are supported:

* **Sync** (``persist_review_candidates_sync``) is called by the rule
  execution engine, which runs on a synchronous ``Session``. It turns the
  in-memory review candidates collected during a run into durable
  ``TraceabilityReviewItem`` rows, applying deduplication.
* **Async** helpers back the FastAPI review-queue endpoints (list / get /
  lifecycle transitions) and run on an ``AsyncSession``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func as sql_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.traceability_review import (
    OPEN_REVIEW_STATUSES,
    REVIEW_STATUS_CLAIMED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_RESOLVED,
    TERMINAL_REVIEW_STATUSES,
    TraceabilityReviewItem,
)


class ReviewTransitionError(ValueError):
    """Raised when a requested status transition is not allowed."""


# Allowed status transitions for the operator workflow.
#   pending  -> claimed | resolved | rejected
#   claimed  -> resolved | rejected | pending (release)
#   resolved -> pending  (reopen, privileged)
#   rejected -> pending  (reopen, privileged)
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    REVIEW_STATUS_PENDING: {REVIEW_STATUS_CLAIMED, REVIEW_STATUS_RESOLVED, REVIEW_STATUS_REJECTED},
    REVIEW_STATUS_CLAIMED: {REVIEW_STATUS_RESOLVED, REVIEW_STATUS_REJECTED, REVIEW_STATUS_PENDING},
    REVIEW_STATUS_RESOLVED: {REVIEW_STATUS_PENDING},
    REVIEW_STATUS_REJECTED: {REVIEW_STATUS_PENDING},
}

# Transitions that require privileged (reopen / override) authority.
_REOPEN_FROM = TERMINAL_REVIEW_STATUSES

# Upper bound on the per-item transition-note history kept in ``meta`` so an
# item that is reopened / re-resolved many times cannot grow its metadata
# JSON without bound.
_MAX_TRANSITION_NOTES = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Sync persistence (rule execution engine)
# ---------------------------------------------------------------------------
def persist_review_candidates_sync(
    db: Session,
    *,
    rule_id: int,
    execution_id: Optional[int],
    candidates: Iterable[dict[str, Any]],
    actor_id: Optional[int] = None,
) -> dict[str, int]:
    """Persist review candidates produced by a rule run.

    Deduplication: while an item for ``(project_id, artifact_id, rule_id,
    node_id)`` is still open (pending/claimed), a rerun refreshes that item
    (reason, priority, latest execution) instead of inserting a duplicate.
    Returns ``{"created": n, "updated": m}``.
    """
    created = 0
    updated = 0
    # Items touched in THIS batch, keyed by the dedup tuple. The sync session
    # runs with autoflush=False, so an unflushed ``db.add()`` is invisible to
    # the per-candidate ``.first()`` lookup below. Without this in-memory guard
    # two candidates sharing (project_id, artifact_id, rule_id, node_id) — e.g.
    # the same artifact reaching one queueReviewAction node twice — would both
    # insert, and the trailing ``db.flush()`` would violate the partial unique
    # index ``uq_traceability_review_items_open`` and abort the whole rule run.
    batch_seen: dict[tuple[Any, ...], TraceabilityReviewItem] = {}

    for candidate in candidates:
        artifact_id = candidate.get("artifact_id")
        # ``bool`` is a subclass of ``int`` — reject it explicitly so a stray
        # boolean id cannot be coerced into artifact_id 0/1.
        if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
            continue
        node_id = candidate.get("node_id") or "unknown"
        project_id = candidate.get("project_id")
        key = (project_id, artifact_id, rule_id, node_id)

        existing = batch_seen.get(key)
        from_db = False
        if existing is None:
            query = db.query(TraceabilityReviewItem).filter(
                TraceabilityReviewItem.artifact_id == artifact_id,
                TraceabilityReviewItem.rule_id == rule_id,
                TraceabilityReviewItem.node_id == node_id,
                TraceabilityReviewItem.status.in_(OPEN_REVIEW_STATUSES),
            )
            if project_id is None:
                query = query.filter(TraceabilityReviewItem.project_id.is_(None))
            else:
                query = query.filter(TraceabilityReviewItem.project_id == project_id)

            existing = query.first()
            from_db = existing is not None

        if existing is not None:
            existing.priority = candidate.get("priority", existing.priority)
            existing.reason = candidate.get("reason", existing.reason)
            existing.rule_execution_id = execution_id
            new_meta = candidate.get("meta")
            if new_meta:
                existing.meta = {**(existing.meta or {}), **new_meta}
            existing.updated_at = _now()
            # Count only a pre-existing DB row as "updated"; refreshing a row we
            # created earlier in this same batch is not a separate update.
            if from_db:
                updated += 1
            batch_seen[key] = existing
            continue

        item = TraceabilityReviewItem(
            tenant_id=candidate.get("tenant_id"),
            project_id=project_id,
            artifact_id=artifact_id,
            rule_id=rule_id,
            rule_execution_id=execution_id,
            node_id=node_id,
            status=REVIEW_STATUS_PENDING,
            priority=candidate.get("priority", "normal"),
            reason=candidate.get("reason"),
            created_by_id=actor_id,
            meta=candidate.get("meta"),
        )
        db.add(item)
        batch_seen[key] = item
        created += 1

    db.flush()
    return {"created": created, "updated": updated}


# ---------------------------------------------------------------------------
# Async query / transition helpers (API layer)
# ---------------------------------------------------------------------------
async def list_review_items(
    db: AsyncSession,
    *,
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    artifact_id: Optional[int] = None,
    rule_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[TraceabilityReviewItem]]:
    """Return ``(total, items)`` for the filtered, paginated review queue."""
    conditions = []
    if project_id is not None:
        conditions.append(TraceabilityReviewItem.project_id == project_id)
    if status is not None:
        conditions.append(TraceabilityReviewItem.status == status)
    if priority is not None:
        conditions.append(TraceabilityReviewItem.priority == priority)
    if artifact_id is not None:
        conditions.append(TraceabilityReviewItem.artifact_id == artifact_id)
    if rule_id is not None:
        conditions.append(TraceabilityReviewItem.rule_id == rule_id)

    base = select(TraceabilityReviewItem)
    if conditions:
        base = base.where(*conditions)

    count_query = select(sql_func.count()).select_from(base.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    rows = (
        (
            await db.execute(
                # ``id`` is the unique tiebreaker: a single rule run inserts many
                # rows with identical ``created_at``, so ordering by timestamp alone
                # is non-deterministic and offset/limit paging could drop or
                # duplicate rows across pages.
                base.order_by(
                    TraceabilityReviewItem.created_at.desc(),
                    TraceabilityReviewItem.id.desc(),
                )
                .offset(skip)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return total, list(rows)


async def get_review_item(
    db: AsyncSession, review_item_id: int, *, for_update: bool = False
) -> Optional[TraceabilityReviewItem]:
    stmt = select(TraceabilityReviewItem).where(TraceabilityReviewItem.id == review_item_id)
    if for_update:
        # Serialize concurrent lifecycle transitions on the same row (e.g. two
        # operators claiming simultaneously). No-op on SQLite; a real row lock
        # on PostgreSQL, so the second transaction sees the post-claim status
        # and is rejected by the transition graph instead of silently winning.
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


def transition_review_item(
    item: TraceabilityReviewItem,
    *,
    target_status: str,
    actor_id: Optional[int],
    note: Optional[str] = None,
) -> TraceabilityReviewItem:
    """Apply a lifecycle transition in place, enforcing the status graph.

    The caller owns the transaction/commit. Raises ``ReviewTransitionError``
    if the transition is not allowed from the current status.
    """
    current = item.status
    allowed = _ALLOWED_TRANSITIONS.get(current, set())
    if target_status not in allowed:
        raise ReviewTransitionError(
            f"Cannot transition review item from '{current}' to '{target_status}'"
        )

    item.status = target_status

    if target_status == REVIEW_STATUS_CLAIMED:
        item.assigned_to_id = actor_id
        item.resolved_at = None
        item.resolved_by_id = None
    elif target_status in (REVIEW_STATUS_RESOLVED, REVIEW_STATUS_REJECTED):
        item.resolved_by_id = actor_id
        item.resolved_at = _now()
    elif target_status == REVIEW_STATUS_PENDING:
        # Back to pending — whether reopened from a terminal state or released
        # from 'claimed', the item is unassigned again, so always clear the
        # assignee along with the resolution fields. (Leaving a stale
        # assigned_to_id made a pending item look claimed while sitting in the
        # open queue.)
        item.resolved_at = None
        item.resolved_by_id = None
        item.assigned_to_id = None

    if note is not None:
        meta = dict(item.meta or {})
        history = list(meta.get("transition_notes", []))
        history.append(
            {
                "from": current,
                "to": target_status,
                "actor_id": actor_id,
                "note": note,
                "at": _now().isoformat(),
            }
        )
        # Cap retained history so reopen/re-resolve cycles cannot grow the
        # metadata JSON (and every API response that serializes it) without
        # bound; keep the most recent entries.
        if len(history) > _MAX_TRANSITION_NOTES:
            history = history[-_MAX_TRANSITION_NOTES:]
        meta["transition_notes"] = history
        item.meta = meta

    item.updated_at = _now()
    return item


def is_reopen(current_status: str, target_status: str) -> bool:
    """True when the transition is a privileged reopen from a terminal state."""
    return current_status in _REOPEN_FROM and target_status == REVIEW_STATUS_PENDING
