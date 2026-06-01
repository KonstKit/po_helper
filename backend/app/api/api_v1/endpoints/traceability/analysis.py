"""Full traceability chain and impact analysis endpoints."""

from __future__ import annotations

from typing import Optional, Dict, Any, List, Set, Tuple

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.config import settings
from app.core.cache_enhanced import (
    CacheTier,
    TraceabilityCacheKeys,
    get_enhanced_cache_service,
)
from app.models import Artifact, ArtifactLink, User, Permissions
from app.api.deps import ensure_project_access, require_permission
from app.utils import get_or_404
from app.utils.confidence import confidence_filter

router = APIRouter()


def _artifact_to_node(artifact: Artifact, level: int, is_center: bool = False) -> Dict[str, Any]:
    """Convert artifact to node dict for D3.js."""
    return {
        "id": artifact.id,
        "type": artifact.type,
        "source": artifact.source,
        "external_id": artifact.external_id,
        "display_key": artifact.display_key or artifact.external_id,
        "title": artifact.title,
        "status": artifact.status,
        "url": artifact.url,
        "level": level,
        "is_center": is_center,
        "meta": artifact.meta or {},
    }


async def _traverse_chain(
    db: AsyncSession,
    start_id: int,
    max_depth: int,
    min_confidence: float,
    include_factors: bool,
    nodes: Dict[int, Dict[str, Any]],
    edges: List[Dict[str, Any]],
    levels: Dict[int, List[int]],
    seen: Set[int],
    is_upstream: bool,
    project_id: Optional[int],
):
    """BFS traversal in one direction (upstream or downstream)."""
    frontier: List[Tuple[int, int]] = [(start_id, 0)]

    while frontier:
        cur_id, dist = frontier.pop(0)
        if dist >= max_depth:
            continue

        if is_upstream:
            link_query = (
                select(ArtifactLink, Artifact)
                .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
                .where(ArtifactLink.to_artifact_id == cur_id)
            )
        else:
            link_query = (
                select(ArtifactLink, Artifact)
                .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
                .where(ArtifactLink.from_artifact_id == cur_id)
            )

        if min_confidence > 0:
            link_query = link_query.where(
                confidence_filter(ArtifactLink.confidence, min_confidence)
            )

        if project_id is not None:
            link_query = link_query.where(ArtifactLink.project_id == project_id)

        res = await db.execute(link_query)

        for link, artifact in res.all():
            new_dist = dist + 1
            level = -new_dist if is_upstream else new_dist

            if artifact.id not in nodes:
                nodes[artifact.id] = _artifact_to_node(artifact, level)
                levels.setdefault(level, []).append(artifact.id)

            edge_data = {
                "from": link.from_artifact_id,
                "to": link.to_artifact_id,
                "link_type": link.link_type,
                "confidence": link.confidence,
                "direction": "upstream" if is_upstream else "downstream",
            }
            if include_factors and link.confidence_factors:
                edge_data["confidence_factors"] = link.confidence_factors

            edges.append(edge_data)

            if artifact.id not in seen:
                seen.add(artifact.id)
                frontier.append((artifact.id, new_dist))


def _calculate_chain_stats(
    nodes: Dict[int, Dict[str, Any]], edges: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Calculate statistics for the traceability chain."""
    type_counts: Dict[str, int] = {}
    link_type_counts: Dict[str, int] = {}
    confidence_values: List[float] = []

    for node in nodes.values():
        art_type = node["type"]
        type_counts[art_type] = type_counts.get(art_type, 0) + 1

    for edge in edges:
        lt = edge["link_type"]
        link_type_counts[lt] = link_type_counts.get(lt, 0) + 1
        if edge["confidence"] is not None:
            confidence_values.append(edge["confidence"])

    return {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "by_artifact_type": type_counts,
        "by_link_type": link_type_counts,
        "confidence": {
            "avg": sum(confidence_values) / len(confidence_values) if confidence_values else None,
            "min": min(confidence_values) if confidence_values else None,
            "max": max(confidence_values) if confidence_values else None,
            "count_with_confidence": len(confidence_values),
        },
    }


@router.get("/full-chain/{artifact_id}")
async def get_full_chain(
    artifact_id: int,
    depth: int = Query(5, ge=1, le=10, description="Max traversal depth"),
    direction: str = Query(
        "both", description="Traversal direction: upstream, downstream, or both"
    ),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    include_factors: bool = Query(True, description="Include confidence factors breakdown"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get full traceability chain for an artifact with bidirectional traversal.

    Returns a graph structure optimized for D3.js visualization.
    """
    start = await get_or_404(db, select(Artifact).where(Artifact.id == artifact_id), "Artifact")

    if start.project_id is not None:
        await ensure_project_access(start.project_id, db, current_user)

    # Check cache (WARM tier = 5 min TTL)
    cache_key = TraceabilityCacheKeys.full_chain(artifact_id, depth, direction, min_confidence)
    cache_service = get_enhanced_cache_service()
    if settings.ENABLE_MATRIX_CACHE:
        cached = await cache_service.get(cache_key, CacheTier.WARM)
        if cached is not None:
            return cached

    nodes: Dict[int, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    levels: Dict[int, List[int]] = {0: [artifact_id]}

    nodes[start.id] = _artifact_to_node(start, level=0, is_center=True)

    seen_upstream: Set[int] = {start.id}
    seen_downstream: Set[int] = {start.id}

    if direction in ("upstream", "both"):
        await _traverse_chain(
            db,
            start.id,
            depth,
            min_confidence,
            include_factors,
            nodes,
            edges,
            levels,
            seen_upstream,
            is_upstream=True,
            project_id=start.project_id,
        )

    if direction in ("downstream", "both"):
        await _traverse_chain(
            db,
            start.id,
            depth,
            min_confidence,
            include_factors,
            nodes,
            edges,
            levels,
            seen_downstream,
            is_upstream=False,
            project_id=start.project_id,
        )

    stats = _calculate_chain_stats(nodes, edges)

    payload = {
        "center_artifact": nodes[artifact_id],
        "nodes": list(nodes.values()),
        "edges": edges,
        "levels": {str(k): v for k, v in sorted(levels.items())},
        "stats": stats,
        "params": {
            "depth": depth,
            "direction": direction,
            "min_confidence": min_confidence,
        },
    }

    # Store in cache
    if settings.ENABLE_MATRIX_CACHE:
        await cache_service.set(cache_key, payload, CacheTier.WARM)

    return payload


def _calculate_impact_risk(
    artifact: Artifact,
    directly_affected: List[Dict],
    indirectly_affected: List[Dict],
    change_type: str,
) -> float:
    """Calculate impact risk score (0-1)."""
    base_risk = 0.1

    direct_count = len(directly_affected)
    if direct_count > 10:
        base_risk += 0.3
    elif direct_count > 5:
        base_risk += 0.2
    elif direct_count > 0:
        base_risk += 0.1

    if change_type == "delete":
        base_risk += 0.3
    elif change_type == "modify":
        base_risk += 0.1

    critical_links = sum(
        1 for d in directly_affected if d.get("link_type") in ("implements", "tests", "deploys")
    )
    if critical_links > 3:
        base_risk += 0.2
    elif critical_links > 0:
        base_risk += 0.1

    if artifact.type in ("requirement", "test_case"):
        base_risk += 0.1

    return min(base_risk, 1.0)


def _risk_level_from_score(risk_score: float) -> str:
    """Bucket the 0-1 impact ``risk_score`` into the level the UI renders.

    This endpoint historically returned only ``risk_score``; the frontend
    Impact Analysis panel reads ``risk_level`` (low/medium/high/critical) for
    its label, colour and icon and crashed (``undefined.toUpperCase()``)
    when the field was absent. Always returning a level keeps the contract whole.
    """
    if risk_score >= 0.8:
        return "critical"
    if risk_score >= 0.6:
        return "high"
    if risk_score >= 0.35:
        return "medium"
    return "low"


def _generate_impact_recommendations(
    artifact: Artifact,
    directly_affected: List[Dict],
    indirectly_affected: List[Dict],
    change_type: str,
    risk_score: float,
) -> List[Dict[str, str]]:
    """Generate recommendations based on impact analysis."""
    recommendations = []

    if risk_score >= 0.7:
        recommendations.append(
            {
                "priority": "high",
                "action": "Review all directly affected artifacts before making changes",
                "reason": f"High impact risk ({risk_score:.1%}) due to many dependencies",
            }
        )

    test_links = [d for d in directly_affected if d.get("link_type") == "tests"]
    if test_links:
        recommendations.append(
            {
                "priority": "high",
                "action": f"Update {len(test_links)} linked test case(s)",
                "reason": "Tests are directly linked and may need updates",
            }
        )

    deploy_links = [d for d in directly_affected if d.get("link_type") == "deploys"]
    if deploy_links:
        recommendations.append(
            {
                "priority": "high",
                "action": "Verify deployment pipeline compatibility",
                "reason": "Deployment artifacts are linked",
            }
        )

    if change_type == "delete":
        recommendations.append(
            {
                "priority": "medium",
                "action": "Consider archiving instead of deleting",
                "reason": "Deletion will break existing links",
            }
        )

    if len(indirectly_affected) > 20:
        recommendations.append(
            {
                "priority": "medium",
                "action": "Notify stakeholders of wide-reaching change",
                "reason": f"{len(indirectly_affected)} artifacts indirectly affected",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "priority": "low",
                "action": "Safe to proceed with change",
                "reason": "Minimal impact detected",
            }
        )

    return recommendations


@router.get("/impact-analysis/{artifact_id}")
async def get_impact_analysis(
    artifact_id: int,
    change_type: str = Query(
        "modify", description="Type of change: modify, delete, or status_change"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Analyze impact of changing an artifact.

    Returns directly_affected, indirectly_affected, risk_score, and recommendations.
    """
    start = await get_or_404(db, select(Artifact).where(Artifact.id == artifact_id), "Artifact")

    if start.project_id is not None:
        await ensure_project_access(start.project_id, db, current_user)

    # Check cache (WARM tier = 5 min TTL)
    cache_key = TraceabilityCacheKeys.impact_analysis(artifact_id, change_type)
    cache_service = get_enhanced_cache_service()
    if settings.ENABLE_MATRIX_CACHE:
        cached = await cache_service.get(cache_key, CacheTier.WARM)
        if cached is not None:
            return cached

    directly_affected: List[Dict[str, Any]] = []
    indirectly_affected: List[Dict[str, Any]] = []

    direct_query = (
        select(ArtifactLink, Artifact)
        .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
        .where(ArtifactLink.from_artifact_id == artifact_id)
    )
    if start.project_id:
        direct_query = direct_query.where(ArtifactLink.project_id == start.project_id)

    direct_res = await db.execute(direct_query)
    direct_ids: Set[int] = set()

    for link, artifact in direct_res.all():
        direct_ids.add(artifact.id)
        directly_affected.append(
            {
                "id": artifact.id,
                "type": artifact.type,
                "display_key": artifact.display_key or artifact.external_id,
                "title": artifact.title,
                "link_type": link.link_type,
                "confidence": link.confidence,
                "impact_level": "high"
                if link.link_type in ("implements", "tests", "deploys")
                else "medium",
            }
        )

    seen = direct_ids | {artifact_id}
    frontier = list(direct_ids)
    depth = 1
    max_depth = 5

    while frontier and depth < max_depth:
        next_frontier = []
        for cur_id in frontier:
            ind_query = (
                select(ArtifactLink, Artifact)
                .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
                .where(ArtifactLink.from_artifact_id == cur_id)
            )
            if start.project_id:
                ind_query = ind_query.where(ArtifactLink.project_id == start.project_id)

            ind_res = await db.execute(ind_query)
            for link, artifact in ind_res.all():
                if artifact.id not in seen:
                    seen.add(artifact.id)
                    next_frontier.append(artifact.id)
                    indirectly_affected.append(
                        {
                            "id": artifact.id,
                            "type": artifact.type,
                            "display_key": artifact.display_key or artifact.external_id,
                            "title": artifact.title,
                            "distance": depth + 1,
                            "impact_level": "low" if depth > 2 else "medium",
                        }
                    )
        frontier = next_frontier
        depth += 1

    risk_score = _calculate_impact_risk(start, directly_affected, indirectly_affected, change_type)
    recommendations = _generate_impact_recommendations(
        start, directly_affected, indirectly_affected, change_type, risk_score
    )

    # --- Normalize to the frontend ImpactAnalysisResponse contract -----------
    # The panel reads impact_type/distance/path on each affected item, a `stats`
    # block (incl. affected_types), and string recommendations. Build those here
    # so the response matches the typed contract the UI was written against
    # (a missing `stats`/`risk_level` previously white-screened the page).
    for _item in directly_affected:
        _item["impact_type"] = "direct"
        _item.setdefault("distance", 1)
        _item["path"] = [start.id, _item["id"]]
    for _item in indirectly_affected:
        _item["impact_type"] = "indirect"
        _item["path"] = [start.id, _item["id"]]

    affected_types: Dict[str, int] = {}
    for _item in directly_affected + indirectly_affected:
        _t = _item.get("type") or "unknown"
        affected_types[_t] = affected_types.get(_t, 0) + 1

    recommendation_texts: List[str] = []
    for _rec in recommendations:
        if isinstance(_rec, dict):
            _action = _rec.get("action", "")
            _reason = _rec.get("reason")
            recommendation_texts.append(f"{_action} — {_reason}" if _reason else _action)
        else:
            recommendation_texts.append(str(_rec))

    payload = {
        "source_artifact_id": start.id,
        "artifact": {
            "id": start.id,
            "type": start.type,
            "display_key": start.display_key or start.external_id,
            "title": start.title,
        },
        "change_type": change_type,
        "directly_affected": directly_affected,
        "indirectly_affected": indirectly_affected,
        "risk_score": risk_score,
        "risk_level": _risk_level_from_score(risk_score),
        "recommendations": recommendation_texts,
        "stats": {
            "total_affected": len(directly_affected) + len(indirectly_affected),
            "direct_count": len(directly_affected),
            "indirect_count": len(indirectly_affected),
            "affected_types": affected_types,
        },
    }

    # Store in cache
    if settings.ENABLE_MATRIX_CACHE:
        await cache_service.set(cache_key, payload, CacheTier.WARM)

    return payload
