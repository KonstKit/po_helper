"""Orphaned artifacts and confidence scoring endpoints."""

from __future__ import annotations

from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, exists, or_

from app.core.database import get_db
from app.core.config import settings
from app.core.cache_enhanced import (
    CacheTier,
    TraceabilityCacheKeys,
    get_enhanced_cache_service,
)
from app.models import Artifact, ArtifactLink, User, Permissions
from app.api.deps import ensure_project_access, require_permission
from app.services.confidence_scoring import confidence_scoring_service
from app.utils.confidence import normalize_confidence, normalized_confidence_column

router = APIRouter()


def _suggest_link_action(artifact: Artifact) -> str:
    """Suggest action for orphaned artifact based on type."""
    suggestions = {
        "requirement": "Link to implementing tasks or test cases",
        "jira_issue": "Link to commits, PRs, or requirements",
        "commit": "Parse commit message for Jira keys",
        "pr": "Extract linked issues from PR description",
        "test_case": "Link to requirement being tested",
        "confluence_page": "Run Confluence autolink to find Jira references",
        "deployment": "Link to pipeline and commits deployed",
    }
    return suggestions.get(artifact.type, "Review and create appropriate links")


@router.get("/orphaned-artifacts")
async def get_orphaned_artifacts(
    project_id: Optional[int] = None,
    artifact_type: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Find artifacts with no incoming or outgoing links (orphans).

    Orphaned artifacts may indicate incomplete traceability, stale items,
    or missing link creation.
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Check cache (COLD tier = 30 min TTL - orphans change rarely)
    cache_key = TraceabilityCacheKeys.orphaned_artifacts(project_id, artifact_type, skip, limit)
    cache_service = get_enhanced_cache_service()
    if settings.ENABLE_MATRIX_CACHE:
        cached = await cache_service.get(cache_key, CacheTier.COLD)
        if cached is not None:
            return cached

    has_outgoing = exists(
        select(ArtifactLink.id).where(ArtifactLink.from_artifact_id == Artifact.id)
    )
    has_incoming = exists(select(ArtifactLink.id).where(ArtifactLink.to_artifact_id == Artifact.id))

    query = select(Artifact).where(~has_outgoing, ~has_incoming)

    if project_id is not None:
        query = query.where(Artifact.project_id == project_id)
    if artifact_type:
        query = query.where(Artifact.type == artifact_type)

    count_query = select(sql_func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(Artifact.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    orphans = result.scalars().all()

    type_summary: Dict[str, int] = {}
    items = []
    for art in orphans:
        type_summary[art.type] = type_summary.get(art.type, 0) + 1
        items.append(
            {
                "id": art.id,
                "type": art.type,
                "source": art.source,
                "external_id": art.external_id,
                "display_key": art.display_key or art.external_id,
                "title": art.title,
                "status": art.status,
                "created_at": art.created_at.isoformat() if art.created_at else None,
                "suggestion": _suggest_link_action(art),
            }
        )

    payload = {
        "total": total,
        "items": items,
        "by_type": type_summary,
        "recommendations": [
            "Run source sync or traceability repair to ensure all artifacts are imported",
            "Execute auto-linking rules to create missing connections",
            "Review orphaned requirements for test coverage gaps",
        ]
        if total > 0
        else [],
    }

    # Store in cache
    if settings.ENABLE_MATRIX_CACHE:
        await cache_service.set(cache_key, payload, CacheTier.COLD)

    return payload


@router.post("/recalculate-confidence")
async def recalculate_link_confidence(
    link_id: Optional[int] = None,
    project_id: Optional[int] = None,
    min_current_confidence: Optional[float] = Query(
        None, description="Only recalculate links with confidence <= this value"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Recalculate confidence scores for existing links.

    Can target a specific link (by link_id), all links in a project (by project_id),
    or links below a confidence threshold.
    """
    if link_id is None and project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if link_id is not None:
        link = await db.get(ArtifactLink, link_id)
        if link is None:
            raise HTTPException(status_code=404, detail="Link not found")
        if link.project_id is not None:
            await ensure_project_access(link.project_id, db, current_user)
    elif project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    query = select(ArtifactLink)

    if link_id is not None:
        query = query.where(ArtifactLink.id == link_id)
    elif project_id is not None:
        query = query.where(ArtifactLink.project_id == project_id)

    if min_current_confidence is not None:
        # Use normalized column to handle legacy 0..100 confidence values
        query = query.where(
            or_(
                normalized_confidence_column(ArtifactLink.confidence) <= min_current_confidence,
                ArtifactLink.confidence.is_(None),
            )
        )

    result = await db.execute(query)
    links = result.scalars().all()

    if not links:
        return {"updated": 0, "message": "No links found matching criteria"}

    artifact_ids = set()
    for link in links:
        artifact_ids.add(link.from_artifact_id)
        artifact_ids.add(link.to_artifact_id)

    artifacts_result = await db.execute(select(Artifact).where(Artifact.id.in_(artifact_ids)))
    artifacts = {a.id: a for a in artifacts_result.scalars().all()}

    updated_count = 0
    results: List[Dict[str, float | int | str | None]] = []

    async with db.begin():
        for link in links:
            from_art = artifacts.get(link.from_artifact_id)
            to_art = artifacts.get(link.to_artifact_id)

            if not from_art or not to_art:
                continue

            from_dict = {
                "id": from_art.id,
                "type": from_art.type,
                "source": from_art.source,
                "external_id": from_art.external_id,
                "display_key": from_art.display_key,
                "title": from_art.title,
                "status": from_art.status,
                "meta": from_art.meta or {},
                "created_at": from_art.created_at,
            }
            to_dict = {
                "id": to_art.id,
                "type": to_art.type,
                "source": to_art.source,
                "external_id": to_art.external_id,
                "display_key": to_art.display_key,
                "title": to_art.title,
                "status": to_art.status,
                "meta": to_art.meta or {},
                "created_at": to_art.created_at,
            }

            new_confidence, factors = confidence_scoring_service.calculate_confidence(
                from_dict, to_dict, link.link_type
            )

            old_confidence = link.confidence
            link.confidence = new_confidence
            link.confidence_factors = factors
            updated_count += 1

            results.append(
                {
                    "link_id": link.id,
                    "old_confidence": old_confidence,
                    "new_confidence": new_confidence,
                    "change": new_confidence - (old_confidence or 0),
                }
            )

    return {
        "updated": updated_count,
        "results": results[:50],
        "summary": {
            "avg_old": (
                sum(float(r.get("old_confidence") or 0) for r in results) / len(results)
                if results
                else 0
            ),
            "avg_new": (
                sum(float(r.get("new_confidence") or 0) for r in results) / len(results)
                if results
                else 0
            ),
        },
    }


@router.get("/confidence-distribution")
async def get_confidence_distribution(
    project_id: Optional[int] = None,
    link_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get distribution of confidence scores for analysis.

    Returns histogram buckets, stats by link type, and low confidence links that need review.
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    query = select(ArtifactLink)
    if project_id is not None:
        query = query.where(ArtifactLink.project_id == project_id)
    if link_type:
        query = query.where(ArtifactLink.link_type == link_type)

    result = await db.execute(query)
    links = result.scalars().all()

    if not links:
        return {
            "histogram": [],
            "stats": {
                "total_links": 0,
                "avg_confidence": 0.0,
                "median_confidence": 0.0,
                "min_confidence": 0.0,
                "max_confidence": 0.0,
            },
            "by_link_type": {},
        }

    histogram = {
        "0.0-0.2": 0,
        "0.2-0.4": 0,
        "0.4-0.6": 0,
        "0.6-0.8": 0,
        "0.8-1.0": 0,
        "no_score": 0,
    }

    by_link_type: Dict[str, Dict[str, Any]] = {}
    scored_confidences: List[float] = []

    for link in links:
        lt = link.link_type
        if lt not in by_link_type:
            by_link_type[lt] = {"count": 0, "sum": 0.0, "no_score": 0}

        by_link_type[lt]["count"] += 1

        # Normalize legacy 0..100 confidence values to 0..1 scale
        conf = normalize_confidence(link.confidence)
        if conf is None:
            histogram["no_score"] += 1
            by_link_type[lt]["no_score"] += 1
        else:
            by_link_type[lt]["sum"] += conf
            scored_confidences.append(conf)

            if conf < 0.2:
                histogram["0.0-0.2"] += 1
            elif conf < 0.4:
                histogram["0.2-0.4"] += 1
            elif conf < 0.6:
                histogram["0.4-0.6"] += 1
            elif conf < 0.8:
                histogram["0.6-0.8"] += 1
            else:
                histogram["0.8-1.0"] += 1

    for lt, stats in by_link_type.items():
        scored = stats["count"] - stats["no_score"]
        stats["avg_confidence"] = stats["sum"] / scored if scored > 0 else 0.0
        del stats["sum"]
        del stats["no_score"]

    scored_confidences.sort()
    median_confidence = 0.0
    if scored_confidences:
        midpoint = len(scored_confidences) // 2
        if len(scored_confidences) % 2 == 0:
            median_confidence = (
                scored_confidences[midpoint - 1] + scored_confidences[midpoint]
            ) / 2
        else:
            median_confidence = scored_confidences[midpoint]

    return {
        "histogram": [
            {"range": range_key, "count": histogram[range_key]}
            for range_key in ("0.0-0.2", "0.2-0.4", "0.4-0.6", "0.6-0.8", "0.8-1.0")
        ],
        "stats": {
            "total_links": len(links),
            "avg_confidence": (
                sum(scored_confidences) / len(scored_confidences)
                if scored_confidences
                else 0.0
            ),
            "median_confidence": median_confidence,
            "min_confidence": scored_confidences[0] if scored_confidences else 0.0,
            "max_confidence": scored_confidences[-1] if scored_confidences else 0.0,
        },
        "by_link_type": by_link_type,
    }
