"""Derivation endpoints for computed/materialized traceability links.

Provides endpoints to:
- Find paths between artifacts
- Compute derived links
- Materialize derived links to database
- Get derivation statistics
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import Artifact, User, Permissions
from app.api.deps import ensure_project_access, require_permission
from app.services.traceability import (
    get_derivation_service,
)

router = APIRouter()


class PathFindingRequest(BaseModel):
    """Request for finding paths between artifacts."""

    start_artifact_id: int
    end_artifact_id: int
    max_depth: int = 5
    link_types: Optional[List[str]] = None
    min_confidence: Optional[float] = None


class DerivedLinksRequest(BaseModel):
    """Request for computing derived links."""

    from_type: str = "requirement"
    to_type: str = "commit"
    via_types: Optional[List[str]] = None
    max_depth: int = 3


class MaterializeRequest(BaseModel):
    """Request for materializing derived links."""

    from_type: str = "requirement"
    to_type: str = "commit"
    via_types: Optional[List[str]] = None
    max_depth: int = 3
    overwrite: bool = False


@router.post("/derivation/find-paths")
async def find_paths_between_artifacts(
    request: PathFindingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Find all paths between two artifacts.

    Returns all possible paths through the traceability graph,
    sorted by confidence and path length.
    """
    # Validate artifacts exist
    result = await db.execute(
        select(Artifact).where(
            Artifact.id.in_([request.start_artifact_id, request.end_artifact_id])
        )
    )
    artifacts = {a.id: a for a in result.scalars().all()}

    if request.start_artifact_id not in artifacts:
        raise HTTPException(status_code=404, detail="Start artifact not found")
    if request.end_artifact_id not in artifacts:
        raise HTTPException(status_code=404, detail="End artifact not found")

    start = artifacts[request.start_artifact_id]
    end = artifacts[request.end_artifact_id]

    # Check project access
    if start.project_id:
        await ensure_project_access(start.project_id, db, current_user)
    if end.project_id and end.project_id != start.project_id:
        await ensure_project_access(end.project_id, db, current_user)

    # Find paths
    service = get_derivation_service(db)
    link_types = set(request.link_types) if request.link_types else None

    paths = await service.find_paths(
        request.start_artifact_id,
        request.end_artifact_id,
        max_depth=request.max_depth,
        link_types=link_types,
        min_confidence=request.min_confidence,
        project_id=start.project_id,
    )

    return {
        "start_artifact": {
            "id": start.id,
            "type": start.type,
            "key": start.display_key or start.external_id,
        },
        "end_artifact": {
            "id": end.id,
            "type": end.type,
            "key": end.display_key or end.external_id,
        },
        "paths_found": len(paths),
        "paths": [
            {
                "path": p.path,
                "links": p.links,
                "link_types": p.link_types,
                "total_confidence": round(p.total_confidence, 4),
                "min_confidence": round(p.min_confidence, 4),
                "length": p.path_length,
            }
            for p in paths
        ],
    }


@router.get("/derivation/reachable/{artifact_id}")
async def find_reachable_artifacts(
    artifact_id: int,
    direction: str = Query("outgoing", description="Direction: outgoing, incoming, or both"),
    max_depth: int = Query(5, ge=1, le=10),
    artifact_types: Optional[str] = Query(None, description="Comma-separated artifact types"),
    link_types: Optional[str] = Query(None, description="Comma-separated link types"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Find all artifacts reachable from a starting artifact.

    Returns a map of reachable artifacts with their shortest paths.
    """
    # Get artifact
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.project_id:
        await ensure_project_access(artifact.project_id, db, current_user)

    # Parse filters
    artifact_type_set = set(artifact_types.split(",")) if artifact_types else None
    link_type_set = set(link_types.split(",")) if link_types else None

    # Find reachable
    service = get_derivation_service(db)
    reachable = await service.find_all_reachable(
        artifact_id,
        direction=direction,
        max_depth=max_depth,
        link_types=link_type_set,
        artifact_types=artifact_type_set,
        project_id=artifact.project_id,
    )

    # Build response
    return {
        "start_artifact_id": artifact_id,
        "direction": direction,
        "max_depth": max_depth,
        "total_reachable": len(reachable),
        "reachable": [
            {
                "artifact_id": path.end_artifact_id,
                "path": path.path,
                "link_types": path.link_types,
                "distance": path.path_length,
                "confidence": round(path.total_confidence, 4),
            }
            for path in reachable.values()
        ],
    }


@router.post("/derivation/compute/{project_id}")
async def compute_derived_links(
    project_id: int,
    request: DerivedLinksRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Compute derived links between artifact types.

    For example: requirement → jira_issue → commit
    Derives: requirement → commit (traced_to)

    Does NOT persist to database - use materialize endpoint for that.
    """
    await ensure_project_access(project_id, db, current_user)

    service = get_derivation_service(db)
    derived = await service.compute_derived_links(
        project_id,
        from_type=request.from_type,
        to_type=request.to_type,
        via_types=request.via_types,
        max_depth=request.max_depth,
    )

    return {
        "project_id": project_id,
        "from_type": request.from_type,
        "to_type": request.to_type,
        "derived_count": len(derived),
        "derived_links": [
            {
                "from_artifact_id": d.from_artifact_id,
                "to_artifact_id": d.to_artifact_id,
                "derived_type": d.derived_type,
                "confidence": round(d.combined_confidence, 4),
                "path_count": len(d.paths),
                "best_path": d.paths[0].to_dict() if d.paths else None,
            }
            for d in derived[:100]  # Limit response size
        ],
        "truncated": len(derived) > 100,
    }


@router.post("/derivation/materialize/{project_id}")
async def materialize_derived_links(
    project_id: int,
    request: MaterializeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Compute and persist derived links to the database.

    Materialized links can be used for faster queries and reporting.
    Use overwrite=true to replace existing derived links.
    """
    await ensure_project_access(project_id, db, current_user)

    service = get_derivation_service(db)

    # Compute
    derived = await service.compute_derived_links(
        project_id,
        from_type=request.from_type,
        to_type=request.to_type,
        via_types=request.via_types,
        max_depth=request.max_depth,
    )

    # Materialize
    created, skipped = await service.materialize_derived_links(
        project_id,
        derived,
        created_by_id=current_user.id,
        overwrite=request.overwrite,
    )

    await db.commit()

    return {
        "project_id": project_id,
        "from_type": request.from_type,
        "to_type": request.to_type,
        "computed": len(derived),
        "created": created,
        "skipped": skipped,
        "overwrite": request.overwrite,
    }


@router.delete("/derivation/invalidate/{artifact_id}")
async def invalidate_derived_links(
    artifact_id: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Invalidate (delete) derived links affected by an artifact change.

    Call this when an artifact or link changes to refresh derived links.
    """
    # Get artifact for project check
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()

    if artifact and artifact.project_id:
        await ensure_project_access(artifact.project_id, db, current_user)
    elif project_id:
        await ensure_project_access(project_id, db, current_user)

    service = get_derivation_service(db)
    deleted = await service.invalidate_derived_links(
        artifact_id,
        project_id=project_id or (artifact.project_id if artifact else None),
    )

    await db.commit()

    return {
        "artifact_id": artifact_id,
        "deleted_count": deleted,
    }


@router.get("/derivation/stats/{project_id}")
async def get_derivation_stats(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get statistics about derived links in a project.
    """
    await ensure_project_access(project_id, db, current_user)

    service = get_derivation_service(db)
    stats = await service.get_derivation_stats(project_id)

    return {
        "project_id": project_id,
        **stats,
    }


@router.post("/derivation/transitive-closure/{project_id}")
async def compute_transitive_closure(
    project_id: int,
    link_type: str = Query(..., description="Link type to compute closure for"),
    max_depth: int = Query(10, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Compute transitive closure for a link type.

    If A implements B and B implements C, then A transitively implements C.

    Returns list of transitive relationships (not persisted).
    """
    await ensure_project_access(project_id, db, current_user)

    service = get_derivation_service(db)
    closure = await service.compute_transitive_closure(
        project_id,
        link_type,
        max_depth=max_depth,
    )

    return {
        "project_id": project_id,
        "link_type": link_type,
        "max_depth": max_depth,
        "transitive_count": len(closure),
        "transitive_links": [
            {"from_id": from_id, "to_id": to_id, "depth": depth}
            for from_id, to_id, depth in closure[:500]  # Limit response
        ],
        "truncated": len(closure) > 500,
    }
