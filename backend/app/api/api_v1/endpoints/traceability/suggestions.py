"""Suggested links endpoints with TF-IDF similarity and approval queue."""

from __future__ import annotations

from typing import Optional, Dict, List, Any, TypedDict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func

from app.core.database import get_db
from app.models import Artifact, User, Permissions
from app.models.traceability import SuggestedLink
from app.api.deps import ensure_project_access, require_permission
from app.services.text_similarity import get_similarity_service
from app.services.traceability.link_service import LinkCreationMethod, LinkService
from app.utils import get_or_404
from app.core.cache_enhanced import CacheInvalidator
from .common import _would_create_cycle, _link_exists

router = APIRouter()


class BulkApproveResult(TypedDict):
    approved: int
    already_processed: int
    cycle_prevented: int
    errors: List[Dict[str, Any]]


@router.post("/suggested-links/generate")
async def generate_link_suggestions(
    project_id: Optional[int] = None,
    min_similarity: float = Query(0.3, ge=0.1, le=1.0, description="Minimum similarity threshold"),
    max_per_artifact: int = Query(5, ge=1, le=20, description="Max suggestions per artifact"),
    artifact_types: Optional[List[str]] = Query(None, description="Artifact types to analyze"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Generate link suggestions using TF-IDF text similarity.

    This analyzes artifact text (titles, descriptions) and finds similar
    artifacts that could be linked but aren't yet.

    Returns:
    - suggestions_created: Number of new suggestions generated
    - duplicates_skipped: Suggestions that already exist
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Get similarity service with custom thresholds
    service = get_similarity_service()
    service.min_similarity = min_similarity
    service.max_suggestions_per_artifact = max_per_artifact

    # Generate suggestions
    suggestions = await service.generate_suggestions(
        db,
        project_id=project_id,
        artifact_types=artifact_types,
        rebuild_index=True,
    )

    if not suggestions:
        return {
            "suggestions_created": 0,
            "message": "No suggestions generated. This could mean artifacts are already well-linked or text similarity is below threshold.",
        }

    # Store suggestions
    stored = await service.store_suggestions(
        db,
        suggestions,
        project_id=project_id,
    )

    return {
        "suggestions_created": stored,
        "total_candidates": len(suggestions),
        "min_similarity_used": min_similarity,
        "message": f"Generated {stored} link suggestions based on text similarity",
    }


@router.get("/suggested-links")
async def list_suggested_links(
    project_id: Optional[int] = None,
    status: str = Query(
        "pending", description="Filter by status: pending, approved, rejected, expired"
    ),
    min_score: Optional[float] = Query(None, ge=0, le=1, description="Minimum similarity score"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    List suggested links with optional filtering.

    Returns paginated list of suggestions with artifact details.
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Build query
    query = select(SuggestedLink)
    conditions = [SuggestedLink.status == status]

    if project_id is not None:
        conditions.append(SuggestedLink.project_id == project_id)
    if min_score is not None:
        conditions.append(SuggestedLink.similarity_score >= min_score)

    query = query.where(*conditions)

    # Get total count
    count_query = select(sql_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Get paginated results
    query = query.order_by(SuggestedLink.similarity_score.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    suggestions = result.scalars().all()

    # Get artifact details
    artifact_ids = set()
    for s in suggestions:
        artifact_ids.add(s.from_artifact_id)
        artifact_ids.add(s.to_artifact_id)

    artifacts_result = await db.execute(select(Artifact).where(Artifact.id.in_(artifact_ids)))
    artifacts = {a.id: a for a in artifacts_result.scalars().all()}

    items = []
    for s in suggestions:
        from_art = artifacts.get(s.from_artifact_id)
        to_art = artifacts.get(s.to_artifact_id)

        items.append(
            {
                "id": s.id,
                "from_artifact": {
                    "id": s.from_artifact_id,
                    "type": from_art.type if from_art else None,
                    "display_key": from_art.display_key or from_art.external_id
                    if from_art
                    else None,
                    "title": from_art.title if from_art else None,
                },
                "to_artifact": {
                    "id": s.to_artifact_id,
                    "type": to_art.type if to_art else None,
                    "display_key": to_art.display_key or to_art.external_id if to_art else None,
                    "title": to_art.title if to_art else None,
                },
                "suggested_link_type": s.suggested_link_type,
                "similarity_score": s.similarity_score,
                "method": s.method,
                "reason": s.reason,
                "status": s.status,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
        )

    return {
        "total": total,
        "items": items,
        "status_filter": status,
    }


@router.post("/suggested-links/{suggestion_id}/approve")
async def approve_suggestion(
    suggestion_id: int,
    note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Approve a suggested link and create the actual artifact link.

    This creates a real ArtifactLink with confidence based on similarity score.
    """
    suggestion = await get_or_404(
        db, select(SuggestedLink).where(SuggestedLink.id == suggestion_id), "Suggested link"
    )

    if suggestion.status != "pending":
        raise HTTPException(status_code=400, detail=f"Suggestion is already {suggestion.status}")

    if suggestion.project_id is not None:
        await ensure_project_access(suggestion.project_id, db, current_user)

    # Check if link already exists
    existing = await _link_exists(
        db,
        suggestion.from_artifact_id,
        suggestion.to_artifact_id,
        suggestion.suggested_link_type,
    )

    if existing:
        # Mark as approved but don't create duplicate
        suggestion.status = "approved"
        suggestion.reviewed_by = current_user.id
        suggestion.reviewed_at = datetime.now(timezone.utc)
        suggestion.review_note = note or "Link already existed"
        await db.commit()

        return {
            "success": True,
            "message": "Link already exists, suggestion marked as approved",
            "link_id": existing.id,
        }

    # Check for cycles
    if await _would_create_cycle(
        db,
        suggestion.from_artifact_id,
        suggestion.to_artifact_id,
        suggestion.suggested_link_type,
        project_id=suggestion.project_id,
    ):
        suggestion.status = "rejected"
        suggestion.reviewed_by = current_user.id
        suggestion.reviewed_at = datetime.now(timezone.utc)
        suggestion.review_note = "Rejected: would create a cycle"
        await db.commit()

        raise HTTPException(status_code=409, detail="Cannot approve: link would create a cycle")

    link_service = LinkService(db)
    new_link = await link_service.create_link(
        suggestion.from_artifact_id,
        suggestion.to_artifact_id,
        suggestion.suggested_link_type,
        project_id=suggestion.project_id,
        tenant_id=suggestion.tenant_id,
        created_by_id=current_user.id,
        created_via=LinkCreationMethod.AUTOLINK,
        confidence=suggestion.similarity_score,
        confidence_factors={
            "method": suggestion.method,
            "auto_suggested": True,
            "similarity_score": suggestion.similarity_score,
            "approved_by_user": True,
        },
        calculate_confidence=False,
    )

    # Update suggestion status
    suggestion.status = "approved"
    suggestion.reviewed_by = current_user.id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    suggestion.review_note = note

    await db.commit()

    # Invalidate traceability caches after link creation
    await CacheInvalidator.on_artifact_link_change(suggestion.project_id)

    return {
        "success": True,
        "message": "Suggestion approved and link created",
        "link_id": new_link.id,
        "link_type": new_link.link_type,
        "confidence": new_link.confidence,
    }


@router.post("/suggested-links/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: int,
    note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Reject a suggested link.

    The suggestion is marked as rejected and won't be shown again.
    """
    suggestion = await get_or_404(
        db, select(SuggestedLink).where(SuggestedLink.id == suggestion_id), "Suggested link"
    )

    if suggestion.status != "pending":
        raise HTTPException(status_code=400, detail=f"Suggestion is already {suggestion.status}")

    if suggestion.project_id is not None:
        await ensure_project_access(suggestion.project_id, db, current_user)

    suggestion.status = "rejected"
    suggestion.reviewed_by = current_user.id
    suggestion.reviewed_at = datetime.now(timezone.utc)
    suggestion.review_note = note

    await db.commit()

    return {
        "success": True,
        "message": "Suggestion rejected",
        "suggestion_id": suggestion_id,
    }


@router.get("/suggested-links/stats")
async def get_suggestion_stats(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get statistics about link suggestions.

    Returns counts by status, method, and link type.
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Build base query
    base_query = select(SuggestedLink)
    if project_id is not None:
        base_query = base_query.where(SuggestedLink.project_id == project_id)

    result = await db.execute(base_query)
    suggestions = result.scalars().all()

    if not suggestions:
        return {
            "total": 0,
            "by_status": {},
            "by_method": {},
            "by_link_type": {},
            "avg_similarity": None,
        }

    # Calculate stats
    by_status: Dict[str, int] = {}
    by_method: Dict[str, int] = {}
    by_link_type: Dict[str, int] = {}
    similarity_scores: List[float] = []

    for s in suggestions:
        by_status[s.status] = by_status.get(s.status, 0) + 1
        by_method[s.method] = by_method.get(s.method, 0) + 1
        by_link_type[s.suggested_link_type] = by_link_type.get(s.suggested_link_type, 0) + 1
        similarity_scores.append(s.similarity_score)

    return {
        "total": len(suggestions),
        "by_status": by_status,
        "by_method": by_method,
        "by_link_type": by_link_type,
        "avg_similarity": sum(similarity_scores) / len(similarity_scores)
        if similarity_scores
        else None,
        "min_similarity": min(similarity_scores) if similarity_scores else None,
        "max_similarity": max(similarity_scores) if similarity_scores else None,
        "approval_rate": (
            by_status.get("approved", 0)
            / (by_status.get("approved", 0) + by_status.get("rejected", 0))
            if (by_status.get("approved", 0) + by_status.get("rejected", 0)) > 0
            else None
        ),
    }


@router.post("/suggested-links/bulk-approve")
async def bulk_approve_suggestions(
    suggestion_ids: List[int],
    note: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Approve multiple suggestions at once.

    Useful for quickly approving high-confidence suggestions.
    """
    if not suggestion_ids:
        raise HTTPException(status_code=400, detail="No suggestion IDs provided")

    if len(suggestion_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 suggestions per bulk operation")

    results: BulkApproveResult = {
        "approved": 0,
        "already_processed": 0,
        "cycle_prevented": 0,
        "errors": [],
    }

    for sugg_id in suggestion_ids:
        try:
            result = await db.execute(select(SuggestedLink).where(SuggestedLink.id == sugg_id))
            suggestion = result.scalar_one_or_none()

            if not suggestion:
                results["errors"].append({"id": sugg_id, "error": "Not found"})
                continue

            if suggestion.status != "pending":
                results["already_processed"] += 1
                continue

            if suggestion.project_id is not None:
                await ensure_project_access(suggestion.project_id, db, current_user)

            # Check for cycles
            if await _would_create_cycle(
                db,
                suggestion.from_artifact_id,
                suggestion.to_artifact_id,
                suggestion.suggested_link_type,
                project_id=suggestion.project_id,
            ):
                suggestion.status = "rejected"
                suggestion.reviewed_by = current_user.id
                suggestion.reviewed_at = datetime.now(timezone.utc)
                suggestion.review_note = "Bulk rejected: would create cycle"
                results["cycle_prevented"] += 1
                continue

            # Check if link already exists
            existing = await _link_exists(
                db,
                suggestion.from_artifact_id,
                suggestion.to_artifact_id,
                suggestion.suggested_link_type,
            )

            if not existing:
                link_service = LinkService(db)
                await link_service.create_link(
                    suggestion.from_artifact_id,
                    suggestion.to_artifact_id,
                    suggestion.suggested_link_type,
                    project_id=suggestion.project_id,
                    tenant_id=suggestion.tenant_id,
                    created_by_id=current_user.id,
                    created_via=LinkCreationMethod.AUTOLINK,
                    confidence=suggestion.similarity_score,
                    confidence_factors={
                        "method": suggestion.method,
                        "auto_suggested": True,
                        "bulk_approved": True,
                    },
                    calculate_confidence=False,
                )

            suggestion.status = "approved"
            suggestion.reviewed_by = current_user.id
            suggestion.reviewed_at = datetime.now(timezone.utc)
            suggestion.review_note = note or "Bulk approved"
            results["approved"] += 1

        except Exception as e:
            results["errors"].append({"id": sugg_id, "error": str(e)})

    await db.commit()

    # Invalidate traceability caches if links were created
    if results["approved"] > 0:
        # Invalidate globally since bulk approve can span projects
        await CacheInvalidator.on_artifact_link_change(None)

    return {
        "success": True,
        "results": results,
        "message": f"Bulk approved {results['approved']} suggestions",
    }
