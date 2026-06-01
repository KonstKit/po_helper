"""Coverage Analytics Service - Requirements coverage analysis.

Provides:
- Uncovered requirements detection
- Coverage trends over time
- Quality gates evaluation
- Gap analysis
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Artifact, ArtifactLink
from app.utils.confidence import normalize_confidence

logger = logging.getLogger(__name__)

# Default quality gate thresholds
DEFAULT_QUALITY_GATES = {
    "min_requirement_coverage_pct": 80.0,
    "min_test_coverage_pct": 70.0,
    "min_avg_confidence": 0.7,
    "max_orphan_requirements_pct": 10.0,
}


async def get_coverage_analytics(
    db: AsyncSession,
    project_id: Optional[int] = None,
    artifact_types: Optional[List[str]] = None,
    include_trends: bool = False,
    trend_days: int = 30,
    quality_gates: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Get comprehensive coverage analytics for a project.

    Args:
        db: Database session
        project_id: Filter by project
        artifact_types: Artifact types to analyze (default: all artifact types in scope)
        include_trends: Include historical trend data
        trend_days: Days of trend data to include
        quality_gates: Custom quality gate thresholds

    Returns:
        Coverage analytics with uncovered items, gaps, trends, and gates
    """
    start = perf_counter()
    logger.info(
        "coverage_analytics.start project_id=%s types=%s",
        project_id,
        artifact_types,
    )

    try:
        # Default to all artifact types in scope when no filter is provided.
        if not artifact_types:
            artifact_types = await _resolve_artifact_types(db, project_id)

        # --- Step 1: Calculate coverage for specified types ---
        coverage_stats = await _calculate_coverage_stats(db, project_id, artifact_types)

        # --- Step 3: Find uncovered requirements ---
        uncovered = await _get_uncovered_artifacts(db, project_id, artifact_types, limit=100)

        # --- Step 4: Gap analysis ---
        gap_analysis = await _analyze_gaps(db, project_id, artifact_types)

        # --- Step 5: Trends (if requested) ---
        trends = None
        if include_trends:
            trends = await _get_coverage_trends(db, project_id, artifact_types, trend_days)

        # --- Step 6: Evaluate quality gates ---
        gates = quality_gates or DEFAULT_QUALITY_GATES
        quality_gate_results = _evaluate_quality_gates(coverage_stats, gap_analysis, gates)

        response = {
            "project_id": project_id,
            "coverage": {
                "total_artifacts": coverage_stats["total"],
                "linked_artifacts": coverage_stats["linked"],
                "unlinked_artifacts": coverage_stats["unlinked"],
                "coverage_pct": coverage_stats["coverage_pct"],
                "by_type": coverage_stats["by_type"],
                "by_link_type": coverage_stats["by_link_type"],
            },
            "uncovered_requirements": [_artifact_to_summary(a) for a in uncovered],
            "gap_analysis": gap_analysis,
            "trends": trends,
            "quality_gates": quality_gate_results,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        duration = perf_counter() - start
        logger.info(
            "coverage_analytics.success project_id=%s coverage=%.1f%% duration=%.3f",
            project_id,
            coverage_stats["coverage_pct"],
            duration,
        )

        return response

    except Exception:
        logger.exception(
            "coverage_analytics.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise


async def _count_artifacts_by_type(
    db: AsyncSession,
    project_id: Optional[int],
) -> Dict[str, int]:
    """Count artifacts grouped by type."""
    stmt = select(Artifact.type, func.count(Artifact.id).label("count")).group_by(Artifact.type)

    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)

    result = await db.execute(stmt)
    return {row.type: row.count for row in result.all()}


async def _resolve_artifact_types(
    db: AsyncSession,
    project_id: Optional[int],
) -> List[str]:
    """Resolve all artifact types in scope, used as default coverage filter."""
    by_type = await _count_artifacts_by_type(db, project_id)
    return sorted(by_type.keys())


async def _calculate_coverage_stats(
    db: AsyncSession,
    project_id: Optional[int],
    artifact_types: List[str],
) -> Dict[str, Any]:
    """Calculate coverage statistics for specified artifact types."""
    # Get artifacts of specified types
    artifact_stmt = select(Artifact.id, Artifact.type).where(Artifact.type.in_(artifact_types))
    if project_id is not None:
        artifact_stmt = artifact_stmt.where(Artifact.project_id == project_id)

    artifact_result = await db.execute(artifact_stmt)
    artifacts = artifact_result.all()

    if not artifacts:
        return {
            "total": 0,
            "linked": 0,
            "unlinked": 0,
            "coverage_pct": 0.0,
            "by_type": {},
            "by_link_type": {},
        }

    artifact_ids = [a.id for a in artifacts]

    # Get links for these artifacts (both directions) including confidence
    link_stmt = select(
        ArtifactLink.from_artifact_id,
        ArtifactLink.to_artifact_id,
        ArtifactLink.link_type,
        ArtifactLink.confidence,
    ).where(
        or_(
            ArtifactLink.from_artifact_id.in_(artifact_ids),
            ArtifactLink.to_artifact_id.in_(artifact_ids),
        )
    )
    if project_id is not None:
        link_stmt = link_stmt.where(ArtifactLink.project_id == project_id)

    link_result = await db.execute(link_stmt)
    links = link_result.all()

    # Determine which artifacts have links and calculate confidence stats
    linked_artifact_ids = set()
    link_type_counts: Dict[str, int] = {}
    confidence_values: List[float] = []

    for link in links:
        if link.from_artifact_id in artifact_ids:
            linked_artifact_ids.add(link.from_artifact_id)
        if link.to_artifact_id in artifact_ids:
            linked_artifact_ids.add(link.to_artifact_id)

        link_type_counts[link.link_type] = link_type_counts.get(link.link_type, 0) + 1

        # Collect normalized confidence values for average calculation
        normalized_conf = normalize_confidence(link.confidence)
        if normalized_conf is not None:
            confidence_values.append(normalized_conf)

    total = len(artifacts)
    linked = len(linked_artifact_ids)
    unlinked = total - linked
    coverage_pct = round((linked / total * 100) if total > 0 else 0.0, 2)

    # Coverage by artifact type
    by_type: Dict[str, Dict[str, Any]] = {}
    for artifact in artifacts:
        atype = artifact.type
        if atype not in by_type:
            by_type[atype] = {"total": 0, "linked": 0, "unlinked": 0, "coverage_pct": 0.0}
        by_type[atype]["total"] += 1
        if artifact.id in linked_artifact_ids:
            by_type[atype]["linked"] += 1
        else:
            by_type[atype]["unlinked"] += 1

    for atype, stats in by_type.items():
        stats["coverage_pct"] = round(
            (stats["linked"] / stats["total"] * 100) if stats["total"] > 0 else 0.0, 2
        )

    # Calculate average confidence
    avg_confidence = (
        round(sum(confidence_values) / len(confidence_values), 3) if confidence_values else None
    )

    return {
        "total": total,
        "linked": linked,
        "unlinked": unlinked,
        "coverage_pct": coverage_pct,
        "by_type": by_type,
        "by_link_type": link_type_counts,
        "avg_confidence": avg_confidence,
    }


async def _get_uncovered_artifacts(
    db: AsyncSession,
    project_id: Optional[int],
    artifact_types: List[str],
    limit: int = 100,
) -> List[Artifact]:
    """Get artifacts that have no links (orphaned)."""
    # Subquery to find artifact IDs that have links
    linked_ids_subquery = (
        select(ArtifactLink.from_artifact_id)
        .where(ArtifactLink.from_artifact_id.isnot(None))
        .union(select(ArtifactLink.to_artifact_id).where(ArtifactLink.to_artifact_id.isnot(None)))
    )

    stmt = (
        select(Artifact)
        .where(Artifact.type.in_(artifact_types))
        .where(Artifact.id.notin_(linked_ids_subquery))
        .order_by(Artifact.created_at.desc())
        .limit(limit)
    )

    if project_id is not None:
        stmt = stmt.where(Artifact.project_id == project_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _analyze_gaps(
    db: AsyncSession,
    project_id: Optional[int],
    artifact_types: List[str],
) -> Dict[str, Any]:
    """Analyze gaps in traceability coverage."""
    # Count by status
    status_stmt = (
        select(Artifact.status, func.count(Artifact.id).label("count"))
        .where(Artifact.type.in_(artifact_types))
        .group_by(Artifact.status)
    )

    if project_id is not None:
        status_stmt = status_stmt.where(Artifact.project_id == project_id)

    status_result = await db.execute(status_stmt)
    by_status = {row.status or "Unknown": row.count for row in status_result.all()}

    # Find artifacts without downstream links (requirements not implemented)
    no_downstream_stmt = select(func.count(Artifact.id)).where(
        Artifact.type.in_(artifact_types),
        Artifact.id.notin_(
            select(ArtifactLink.from_artifact_id).where(
                ArtifactLink.link_type.in_(["implements", "tests", "deploys"])
            )
        ),
    )
    if project_id is not None:
        no_downstream_stmt = no_downstream_stmt.where(Artifact.project_id == project_id)

    no_downstream = (await db.execute(no_downstream_stmt)).scalar() or 0

    # Count artifacts by source
    source_stmt = (
        select(Artifact.source, func.count(Artifact.id).label("count"))
        .where(Artifact.type.in_(artifact_types))
        .group_by(Artifact.source)
    )

    if project_id is not None:
        source_stmt = source_stmt.where(Artifact.project_id == project_id)

    source_result = await db.execute(source_stmt)
    by_source = {row.source: row.count for row in source_result.all()}

    return {
        "by_status": by_status,
        "by_source": by_source,
        "without_downstream_links": no_downstream,
        "potential_gaps": [
            {
                "type": "unimplemented_requirements",
                "count": no_downstream,
                "description": "Requirements without implementation links",
            }
        ],
    }


async def _get_coverage_trends(
    db: AsyncSession,
    project_id: Optional[int],
    artifact_types: List[str],
    days: int = 30,
) -> Dict[str, Any]:
    """Get coverage trends over time."""
    # Note: This is a simplified implementation.
    # A full implementation would track historical snapshots.
    # For now, we return artifact creation trends.

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    # Count new artifacts by day
    new_artifacts_stmt = (
        select(
            func.date(Artifact.created_at).label("date"),
            func.count(Artifact.id).label("count"),
        )
        .where(
            Artifact.type.in_(artifact_types),
            Artifact.created_at >= start_date,
        )
        .group_by(func.date(Artifact.created_at))
        .order_by(func.date(Artifact.created_at))
    )

    if project_id is not None:
        new_artifacts_stmt = new_artifacts_stmt.where(Artifact.project_id == project_id)

    new_result = await db.execute(new_artifacts_stmt)
    daily_new = [{"date": str(row.date), "new_artifacts": row.count} for row in new_result.all()]

    # Count new links by day
    new_links_stmt = (
        select(
            func.date(ArtifactLink.created_at).label("date"),
            func.count(ArtifactLink.id).label("count"),
        )
        .where(ArtifactLink.created_at >= start_date)
        .group_by(func.date(ArtifactLink.created_at))
        .order_by(func.date(ArtifactLink.created_at))
    )

    if project_id is not None:
        new_links_stmt = new_links_stmt.where(ArtifactLink.project_id == project_id)

    links_result = await db.execute(new_links_stmt)
    daily_links = [{"date": str(row.date), "new_links": row.count} for row in links_result.all()]

    return {
        "period_days": days,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily_artifacts": daily_new,
        "daily_links": daily_links,
    }


def _evaluate_quality_gates(
    coverage_stats: Dict[str, Any],
    gap_analysis: Dict[str, Any],
    gates: Dict[str, float],
) -> Dict[str, Any]:
    """Evaluate quality gates against current metrics."""
    results: Dict[str, Any] = {}
    gate_details: Dict[str, Dict[str, Any]] = {}

    by_type = coverage_stats.get("by_type", {})
    requirement_stats = by_type.get("requirement", {})

    # Requirement coverage gate
    min_req_coverage = gates.get("min_requirement_coverage_pct", 80.0)
    req_total = int(requirement_stats.get("total", 0)) if requirement_stats else 0
    req_coverage = float(requirement_stats.get("coverage_pct", 0.0)) if req_total > 0 else 0.0
    results["requirement_coverage"] = req_coverage >= min_req_coverage if req_total > 0 else True
    gate_details["requirement_coverage"] = {
        "actual": req_coverage,
        "threshold": min_req_coverage,
        "passed": results["requirement_coverage"],
        "has_requirements": req_total > 0,
    }

    # Test coverage gate (coverage of test_case type artifacts)
    min_test_coverage = gates.get("min_test_coverage_pct", 70.0)
    test_type_stats = by_type.get("test_case", {})
    test_coverage = test_type_stats.get("coverage_pct", 0.0) if test_type_stats else 0.0
    # Only evaluate if test_case artifacts exist
    if test_type_stats and test_type_stats.get("total", 0) > 0:
        results["test_coverage"] = test_coverage >= min_test_coverage
    else:
        results["test_coverage"] = True  # Pass if no test cases to evaluate
    gate_details["test_coverage"] = {
        "actual": test_coverage,
        "threshold": min_test_coverage,
        "passed": results["test_coverage"],
        "has_test_cases": bool(test_type_stats and test_type_stats.get("total", 0) > 0),
    }

    # Average confidence gate
    min_avg_confidence = gates.get("min_avg_confidence", 0.7)
    avg_confidence = coverage_stats.get("avg_confidence")
    # Only evaluate if we have confidence data
    if avg_confidence is not None:
        results["avg_confidence"] = avg_confidence >= min_avg_confidence
    else:
        results["avg_confidence"] = True  # Pass if no confidence data
    gate_details["avg_confidence"] = {
        "actual": avg_confidence,
        "threshold": min_avg_confidence,
        "passed": results["avg_confidence"],
        "has_confidence_data": avg_confidence is not None,
    }

    # Orphan requirements gate
    max_orphan_pct = gates.get("max_orphan_requirements_pct", 10.0)
    req_unlinked = int(requirement_stats.get("unlinked", 0)) if req_total > 0 else 0
    orphan_pct = round((req_unlinked / req_total * 100), 2) if req_total > 0 else 0.0
    results["orphan_threshold"] = orphan_pct <= max_orphan_pct if req_total > 0 else True
    gate_details["orphan_threshold"] = {
        "actual": orphan_pct,
        "threshold": max_orphan_pct,
        "passed": results["orphan_threshold"],
        "has_requirements": req_total > 0,
    }

    # All gates passed?
    results["all_passed"] = all(v for k, v in results.items() if k != "all_passed")
    results["details"] = gate_details

    return results


def _artifact_to_summary(artifact: Artifact) -> Dict[str, Any]:
    """Convert artifact to summary dict."""
    return {
        "id": artifact.id,
        "type": artifact.type,
        "source": artifact.source,
        "external_id": artifact.external_id,
        "display_key": artifact.display_key,
        "title": artifact.title,
        "status": artifact.status,
        "url": artifact.url,
    }
