"""Traceability manual-review queue endpoints (plan_70).

Lifecycle: pending -> claimed -> resolved | rejected, with privileged reopen
back to pending. RBAC:

* view   -> ``TRACEABILITY_VIEW``
* claim / resolve / reject -> ``TRACEABILITY_MANAGE``
* reopen (from a terminal state) -> ``TRACEABILITY_MANAGE`` + administrator

Every transition is recorded in the shared traceability audit log.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_project_access, require_permission
from app.core.database import get_db
from app.models import Permissions, User
from app.models.traceability_review import (
    REVIEW_PRIORITIES,
    REVIEW_STATUS_CLAIMED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVIEW_STATUS_RESOLVED,
    REVIEW_STATUSES,
)
from app.schemas.traceability_review import (
    ReviewItemListResponse,
    ReviewItemResponse,
    ReviewTransitionRequest,
)
from app.services.audit_log import record_audit_event
from app.services.traceability import review_service
from app.utils import transactional_session

router = APIRouter()


async def _get_item_or_404(db: AsyncSession, review_item_id: int, *, for_update: bool = False):
    item = await review_service.get_review_item(db, review_item_id, for_update=for_update)
    if item is None:
        raise HTTPException(status_code=404, detail=f"Review item {review_item_id} not found")
    return item


@router.get("/review-items", response_model=ReviewItemListResponse)
async def list_review_items(
    project_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None, description="pending|claimed|resolved|rejected"),
    priority: Optional[str] = Query(None),
    artifact_id: Optional[int] = Query(None),
    rule_id: Optional[int] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """List manual-review work items with filtering and bounded pagination."""
    if status is not None and status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status '{status}'")
    if priority is not None and priority not in REVIEW_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority '{priority}'")
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    total, items = await review_service.list_review_items(
        db,
        project_id=project_id,
        status=status,
        priority=priority,
        artifact_id=artifact_id,
        rule_id=rule_id,
        skip=skip,
        limit=limit,
    )
    return ReviewItemListResponse(total=total, items=[ReviewItemResponse.from_db(i) for i in items])


@router.get("/review-items/{review_item_id}", response_model=ReviewItemResponse)
async def get_review_item(
    review_item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    item = await _get_item_or_404(db, review_item_id)
    if item.project_id is not None:
        await ensure_project_access(item.project_id, db, current_user)
    return ReviewItemResponse.from_db(item)


async def _apply_transition(
    *,
    db: AsyncSession,
    current_user: User,
    review_item_id: int,
    target_status: str,
    note: Optional[str],
    audit_action: str,
):
    # Lock the row so concurrent transitions (e.g. two simultaneous claims)
    # serialize: the second transaction observes the post-transition status and
    # is rejected by the transition graph instead of silently winning.
    item = await _get_item_or_404(db, review_item_id, for_update=True)
    if item.project_id is not None:
        await ensure_project_access(item.project_id, db, current_user)

    # Privileged transitions back to 'pending' require administrator rights:
    #   * reopening a terminal (resolved/rejected) item, and
    #   * releasing a claim held by ANOTHER operator.
    # An operator may release their own claim without elevation.
    is_admin = current_user.is_superuser or current_user.has_permission(Permissions.ADMIN)
    reopen_terminal = review_service.is_reopen(item.status, target_status)
    release_others_claim = (
        target_status == REVIEW_STATUS_PENDING
        and item.status == REVIEW_STATUS_CLAIMED
        and item.assigned_to_id is not None
        and item.assigned_to_id != current_user.id
    )
    if (reopen_terminal or release_others_claim) and not is_admin:
        raise HTTPException(
            status_code=403,
            detail=(
                "Reopening a terminal review item or releasing another "
                "operator's claim requires administrator rights"
            ),
        )

    previous_status = item.status
    try:
        async with transactional_session(db):
            review_service.transition_review_item(
                item,
                target_status=target_status,
                actor_id=current_user.id,
                note=note,
            )
            await record_audit_event(
                db,
                action=audit_action,
                entity_type="traceability_review_item",
                entity_id=item.id,
                actor_id=current_user.id,
                project_id=item.project_id,
                payload={
                    "from": previous_status,
                    "to": target_status,
                    "artifact_id": item.artifact_id,
                    "rule_id": item.rule_id,
                    "note": note,
                },
            )
    except review_service.ReviewTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await db.refresh(item)
    return ReviewItemResponse.from_db(item)


@router.post("/review-items/{review_item_id}/claim", response_model=ReviewItemResponse)
async def claim_review_item(
    review_item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Claim a pending review item (assign it to the current operator)."""
    return await _apply_transition(
        db=db,
        current_user=current_user,
        review_item_id=review_item_id,
        target_status=REVIEW_STATUS_CLAIMED,
        note=None,
        audit_action="review_claim",
    )


@router.post("/review-items/{review_item_id}/resolve", response_model=ReviewItemResponse)
async def resolve_review_item(
    review_item_id: int,
    payload: ReviewTransitionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Resolve a review item (operator handled the flagged artifact)."""
    return await _apply_transition(
        db=db,
        current_user=current_user,
        review_item_id=review_item_id,
        target_status=REVIEW_STATUS_RESOLVED,
        note=(payload.note if payload else None),
        audit_action="review_resolve",
    )


@router.post("/review-items/{review_item_id}/reject", response_model=ReviewItemResponse)
async def reject_review_item(
    review_item_id: int,
    payload: ReviewTransitionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Reject a review item (no action needed / not a real concern)."""
    return await _apply_transition(
        db=db,
        current_user=current_user,
        review_item_id=review_item_id,
        target_status=REVIEW_STATUS_REJECTED,
        note=(payload.note if payload else None),
        audit_action="review_reject",
    )


@router.post("/review-items/{review_item_id}/reopen", response_model=ReviewItemResponse)
async def reopen_review_item(
    review_item_id: int,
    payload: ReviewTransitionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Reopen a terminal (resolved/rejected) review item. Administrator only."""
    return await _apply_transition(
        db=db,
        current_user=current_user,
        review_item_id=review_item_id,
        target_status=REVIEW_STATUS_PENDING,
        note=(payload.note if payload else None),
        audit_action="review_reopen",
    )
