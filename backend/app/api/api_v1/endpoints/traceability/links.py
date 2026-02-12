"""Core linking endpoints: create links, get artifacts, flow graph, matrix, backfill."""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db, AsyncSessionLocal
from app.models import Artifact, ArtifactLink, Task, ConfluencePage, User, Permissions
from app.core.config import settings
from app.api.deps import ensure_project_access, require_permission
from app.core.rate_limit import limiter
from app.core.cache_enhanced import (
    CacheTier,
    TraceabilityCacheKeys,
    get_enhanced_cache_service,
    CacheInvalidator,
)
from app.services.confluence_service import confluence_service
from app.services.git_import_service import git_import_service
from app.services.traceability.link_service import LinkService, LinkCreationMethod
from app.utils import get_or_404, execute_with_lock
from app.utils.batch_operations import traverse_graph_batched

from .common import logger

router = APIRouter()


async def _call_confluence(func, *args, **kwargs):
    """Run blocking Confluence service calls off the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


@router.post("/link")
async def create_link(
    from_id: int,
    to_id: int,
    link_type: str,
    confidence: Optional[float] = None,
    confidence_factors: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Create a link between two artifacts.

    Uses LinkService for proper provenance tracking and audit logging.
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Validate artifact access (for project-level permissions)
    res = await db.execute(select(Artifact).where(Artifact.id.in_([from_id, to_id])))
    found = {a.id: a for a in res.scalars().all()}
    if from_id not in found or to_id not in found:
        raise HTTPException(status_code=404, detail="Artifact(s) not found")

    if project_id is None:
        project_ids = {artifact.project_id for artifact in found.values() if artifact.project_id}
        for proj in sorted(project_ids):
            await ensure_project_access(proj, db, current_user)
        # Use first project_id from artifacts if not specified
        project_id = found[from_id].project_id or found[to_id].project_id

    try:
        link_service = LinkService(db)
        link = await link_service.create_link(
            from_artifact_id=from_id,
            to_artifact_id=to_id,
            link_type=link_type,
            tenant_id=tenant_id,
            project_id=project_id,
            created_by_id=current_user.id,
            created_via=LinkCreationMethod.MANUAL,
            confidence=confidence,
            confidence_factors=confidence_factors,
            calculate_confidence=(confidence is None),
            create_audit=True,
        )
        await db.commit()
    except ValueError as e:
        error_msg = str(e)
        if "cycle" in error_msg.lower():
            raise HTTPException(status_code=409, detail="Link would create a cycle")
        if "already exists" in error_msg.lower():
            raise HTTPException(status_code=409, detail="Link already exists")
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)

    # Invalidate traceability caches for affected project
    await CacheInvalidator.on_artifact_link_change(project_id)

    return {"id": link.id, "status": "ok"}


@router.get("/task/{jira_key}/artifacts")
async def artifacts_for_task(
    jira_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Return artifact for task (jira_issue) and its immediate neighbors."""
    task_art = await get_or_404(
        db,
        select(Artifact).where(Artifact.type == "jira_issue", Artifact.external_id == jira_key),
        "Artifact for jira_key",
    )

    if task_art.project_id is not None:
        await ensure_project_access(task_art.project_id, db, current_user)

    outgoing = await db.execute(
        select(ArtifactLink, Artifact)
        .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
        .where(ArtifactLink.from_artifact_id == task_art.id)
    )
    incoming = await db.execute(
        select(ArtifactLink, Artifact)
        .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
        .where(ArtifactLink.to_artifact_id == task_art.id)
    )
    out = [
        {
            "link_type": link.link_type,
            "confidence": link.confidence,
            "artifact": {
                "id": a.id,
                "type": a.type,
                "source": a.source,
                "external_id": a.external_id,
                "title": a.title,
                "status": a.status,
            },
        }
        for (link, a) in outgoing.all()
    ]
    inc = [
        {
            "link_type": link.link_type,
            "confidence": link.confidence,
            "artifact": {
                "id": a.id,
                "type": a.type,
                "source": a.source,
                "external_id": a.external_id,
                "title": a.title,
                "status": a.status,
            },
        }
        for (link, a) in incoming.all()
    ]
    return {
        "task_artifact": {"id": task_art.id, "key": task_art.display_key or task_art.external_id},
        "outgoing": out,
        "incoming": inc,
    }


@router.get("/requirement/{artifact_id}/flow")
async def requirement_flow(
    artifact_id: int,
    depth: int = 3,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Return a BFS flow graph from a requirement artifact up to given depth."""
    depth = max(1, min(depth, 6))

    start = await get_or_404(db, select(Artifact).where(Artifact.id == artifact_id), "Artifact")

    if start.project_id is not None:
        await ensure_project_access(start.project_id, db, current_user)

    nodes_dict, edges_list = await traverse_graph_batched(
        db=db,
        node_model=Artifact,
        link_model=ArtifactLink,
        start_id=start.id,
        from_column="from_artifact_id",
        to_column="to_artifact_id",
        max_depth=depth,
        project_id=start.project_id,
    )

    nodes = [
        {"id": node.id, "type": node.type, "title": node.title, "status": node.status}
        for node in nodes_dict.values()
    ]

    return {"nodes": nodes, "edges": edges_list}


@router.get("/matrix")
async def traceability_matrix(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Return a lightweight coverage-style matrix summary for a project."""
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Check enhanced cache (WARM tier = 5 min TTL)
    cache_key = TraceabilityCacheKeys.matrix(project_id)
    cache_service = get_enhanced_cache_service()
    if settings.ENABLE_MATRIX_CACHE:
        cached = await cache_service.get(cache_key, CacheTier.WARM)
        if cached is not None:
            return cached

    artifacts_stmt = select(Artifact)
    if project_id is not None:
        artifacts_stmt = artifacts_stmt.where(Artifact.project_id == project_id)
    res = await db.execute(artifacts_stmt)
    artifacts = res.scalars().all()

    artifact_count = len(artifacts)
    if artifact_count == 0:
        payload = {
            "total": 0,
            "by_type": {},
            "per_type": {},
            "coverage": {"linked_artifacts": 0, "coverage_pct": 0.0},
        }
        if settings.ENABLE_MATRIX_CACHE:
            await cache_service.set(cache_key, payload, CacheTier.WARM)
        return payload

    artifact_ids = [art.id for art in artifacts]

    # Query outgoing links (from_artifact_id in our set)
    outgoing_stmt = select(ArtifactLink.from_artifact_id, ArtifactLink.link_type)
    outgoing_stmt = outgoing_stmt.where(ArtifactLink.from_artifact_id.in_(artifact_ids))
    res_outgoing = await db.execute(outgoing_stmt)
    raw_outgoing = res_outgoing.all()

    # Query incoming links (to_artifact_id in our set)
    incoming_stmt = select(ArtifactLink.to_artifact_id, ArtifactLink.link_type)
    incoming_stmt = incoming_stmt.where(ArtifactLink.to_artifact_id.in_(artifact_ids))
    res_incoming = await db.execute(incoming_stmt)
    raw_incoming = res_incoming.all()

    # Build link totals and types per artifact (both directions)
    outgoing_link_totals: Dict[int, int] = {}
    outgoing_link_types: Dict[int, Dict[str, int]] = {}
    incoming_link_totals: Dict[int, int] = {}
    incoming_link_types: Dict[int, Dict[str, int]] = {}

    for from_id, link_type in raw_outgoing:
        outgoing_link_totals[from_id] = outgoing_link_totals.get(from_id, 0) + 1
        type_bucket = outgoing_link_types.setdefault(from_id, {})
        type_bucket[link_type] = type_bucket.get(link_type, 0) + 1

    for to_id, link_type in raw_incoming:
        incoming_link_totals[to_id] = incoming_link_totals.get(to_id, 0) + 1
        type_bucket = incoming_link_types.setdefault(to_id, {})
        type_bucket[link_type] = type_bucket.get(link_type, 0) + 1

    by_type: Dict[str, int] = {}
    per_type: Dict[str, Dict[str, Any]] = {}
    linked_artifact_count = 0

    for art in artifacts:
        art_type = art.type
        by_type[art_type] = by_type.get(art_type, 0) + 1
        stats = per_type.setdefault(
            art_type,
            {
                "total": 0,
                "linked": 0,
                "unlinked": 0,
                "link_count": 0.0,
                "outgoing_count": 0.0,
                "incoming_count": 0.0,
                "coverage_pct": 0.0,
                "avg_links_per_artifact": 0.0,
                "link_type_counts": {},
                "link_type_artifact_counts": {},
            },
        )
        stats["total"] += 1

        # Count both outgoing AND incoming links for coverage
        outgoing_links = outgoing_link_totals.get(art.id, 0)
        incoming_links = incoming_link_totals.get(art.id, 0)
        total_links = outgoing_links + incoming_links

        stats["link_count"] += float(total_links)
        stats["outgoing_count"] += float(outgoing_links)
        stats["incoming_count"] += float(incoming_links)

        # Artifact is "linked" if it has ANY link (outgoing OR incoming)
        if total_links > 0:
            stats["linked"] += 1
            linked_artifact_count += 1
        else:
            stats["unlinked"] += 1

        # Aggregate link type counts (both directions)
        for link_type, count in outgoing_link_types.get(art.id, {}).items():
            type_counts = stats["link_type_counts"]
            type_counts[link_type] = type_counts.get(link_type, 0) + count
            artifact_count_map = stats["link_type_artifact_counts"]
            artifact_count_map[link_type] = artifact_count_map.get(link_type, 0) + 1

        for link_type, count in incoming_link_types.get(art.id, {}).items():
            # Prefix incoming link types for clarity
            incoming_key = f"incoming_{link_type}"
            type_counts = stats["link_type_counts"]
            type_counts[incoming_key] = type_counts.get(incoming_key, 0) + count
            # Track artifact counts for incoming types too
            artifact_count_map = stats["link_type_artifact_counts"]
            artifact_count_map[incoming_key] = artifact_count_map.get(incoming_key, 0) + 1

    for stats in per_type.values():
        total = stats["total"] or 1
        stats["coverage_pct"] = (stats["linked"] / total) * 100.0
        stats["avg_links_per_artifact"] = stats["link_count"] / total if total else 0.0
        stats["link_type_counts"] = dict(sorted(stats["link_type_counts"].items()))
        stats["link_type_artifact_counts"] = dict(
            sorted(stats["link_type_artifact_counts"].items())
        )

    payload = {
        "total": len(artifacts),
        "by_type": by_type,
        "per_type": per_type,
        "coverage": {
            "linked_artifacts": linked_artifact_count,
            "coverage_pct": (linked_artifact_count / len(artifacts) * 100.0) if artifacts else 0.0,
        },
    }

    if settings.ENABLE_MATRIX_CACHE:
        await cache_service.set(cache_key, payload, CacheTier.WARM)

    return payload


@router.post("/backfill")
@limiter.limit("5/minute")
async def backfill_artifacts(
    request: Request,
    project_id: int,
    include_confluence: bool = True,
    include_git: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Project backfill: project tasks and optionally Confluence pages to artifacts."""
    await ensure_project_access(project_id, db, current_user)
    if db.in_transaction():
        await db.rollback()

    created = 0
    updated = 0

    try:
        async with db.begin():
            res = await db.execute(select(Task).where(Task.project_id == project_id))
            tasks = res.scalars().all()
            for task in tasks:
                key = task.key or task.jira_id
                if not key:
                    continue
                sel = select(Artifact).where(
                    Artifact.project_id == project_id,
                    Artifact.type == "jira_issue",
                    Artifact.source == "jira",
                    Artifact.external_id == str(key),
                    Artifact.version == 1,
                )
                artifact = (await execute_with_lock(db, sel)).scalar_one_or_none()
                if artifact is None:
                    artifact = Artifact(
                        project_id=project_id,
                        type="jira_issue",
                        source="jira",
                        external_id=str(key),
                        display_key=str(key),
                        title=task.summary,
                        status=task.status,
                        meta={
                            "jira_id": task.jira_id,
                            "priority": task.priority,
                            "assignee_email": task.assignee_email,
                        },
                    )
                    db.add(artifact)
                    created += 1
                else:
                    artifact.title = task.summary
                    artifact.status = task.status
                    updated += 1

            if include_confluence:
                pages_result = await db.execute(select(ConfluencePage))
                pages: List[ConfluencePage] = list(pages_result.scalars().all())
                for page in pages:
                    selp = select(Artifact).where(
                        Artifact.type == "confluence_page",
                        Artifact.source == "confluence",
                        Artifact.external_id == str(page.confluence_id),
                        Artifact.version == 1,
                        Artifact.project_id == project_id,
                    )
                    artifact = (await execute_with_lock(db, selp)).scalar_one_or_none()
                    if artifact is None:
                        artifact = Artifact(
                            project_id=project_id,
                            type="confluence_page",
                            source="confluence",
                            external_id=str(page.confluence_id),
                            display_key=str(page.confluence_id),
                            title=page.title,
                            status=None,
                            url=page.url,
                            meta={"space_key": page.space_key, "page_type": page.page_type},
                        )
                        db.add(artifact)
                        created += 1
                    else:
                        artifact.title = page.title
                        artifact.url = page.url
                        updated += 1
    except IntegrityError:
        await db.rollback()
        pass

    git_result = None
    if include_git:
        try:
            async with AsyncSessionLocal() as git_db:
                git_result = await git_import_service.sync_project(
                    git_db,
                    project_id,
                    include_commits=True,
                    include_pull_requests=True,
                    trigger="manual",
                )
        except Exception as exc:
            logger.error("Git import failed for project %s: %s", project_id, exc)
            git_result = {"error": str(exc)}

    payload: Dict[str, Any] = {"status": "ok", "created": created, "updated": updated}
    if git_result is not None:
        payload["git"] = git_result

    # Invalidate traceability caches after backfill
    await CacheInvalidator.on_artifact_link_change(project_id)

    return JSONResponse(content=payload)


@router.post("/autolink/confluence/{page_id}")
async def autolink_confluence_page(
    page_id: str,
    project_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Parse a Confluence page, detect Jira keys, and create links."""
    if not settings.ENABLE_CONFLUENCE_AUTOLINK:
        raise HTTPException(
            status_code=400, detail="Feature ENABLE_CONFLUENCE_AUTOLINK is disabled"
        )

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    page = await _call_confluence(
        confluence_service.get_page_by_id,
        page_id,
        expand="body.storage,version,metadata.labels",
    )
    html = (page.get("body") or {}).get("storage", {}).get("value") or ""
    key_contexts = confluence_service.extract_jira_keys_from_page(html)
    if not key_contexts:
        return {"page_id": page_id, "created": 0, "updated": 0, "suggestions": []}

    page_stmt = select(Artifact).where(
        Artifact.type == "confluence_page",
        Artifact.source == "confluence",
        Artifact.external_id == str(page_id),
    )
    if project_id is not None:
        page_stmt = page_stmt.where(Artifact.project_id == project_id)
    res = await db.execute(page_stmt)
    page_art = res.scalar_one_or_none()
    checked_project_ids: set[int] = set()
    if project_id is None and page_art and page_art.project_id is not None:
        await ensure_project_access(page_art.project_id, db, current_user)
        checked_project_ids.add(page_art.project_id)

    created = 0
    updated = 0
    suggestions: List[dict] = []

    for jc in key_contexts:
        ctx_lower = (jc.context or "").lower()
        link_type = (
            "implements"
            if any(
                k in ctx_lower
                for k in ["implement", "requirement", "acceptance criteria", "design", "solution"]
            )
            else "relates_to"
        )
        base = 0.6
        if jc.in_link:
            base += 0.2
        if jc.in_header:
            base += 0.1
        if any(k in ctx_lower for k in ["requirement", "acceptance", "jira"]):
            base += 0.05
        confidence = min(base, 0.95)
        factors = {
            "in_link": float(jc.in_link),
            "in_header": float(jc.in_header),
            "context_terms": {
                "requirement": float("requirement" in ctx_lower),
                "acceptance": float("acceptance" in ctx_lower),
            },
        }

        issue_stmt = select(Artifact).where(
            Artifact.type == "jira_issue",
            Artifact.source == "jira",
            Artifact.external_id == jc.key,
        )
        if project_id is not None:
            issue_stmt = issue_stmt.where(Artifact.project_id == project_id)
        res_issue = await db.execute(issue_stmt)
        issue_art = res_issue.scalar_one_or_none()
        if (
            project_id is None
            and issue_art
            and issue_art.project_id is not None
            and issue_art.project_id not in checked_project_ids
        ):
            await ensure_project_access(issue_art.project_id, db, current_user)
            checked_project_ids.add(issue_art.project_id)

        if not page_art or not issue_art:
            suggestions.append(
                {
                    "jira_key": jc.key,
                    "link_type": link_type,
                    "confidence": confidence,
                    "reason": "artifact_missing",
                    "page_artifact_exists": bool(page_art),
                    "issue_artifact_exists": bool(issue_art),
                }
            )
            continue

        try:
            async with db.begin():
                sel = select(ArtifactLink).where(
                    ArtifactLink.from_artifact_id == page_art.id,
                    ArtifactLink.to_artifact_id == issue_art.id,
                    ArtifactLink.link_type == link_type,
                )
                link = (await execute_with_lock(db, sel)).scalar_one_or_none()
                if link is None:
                    link = ArtifactLink(
                        from_artifact_id=page_art.id,
                        to_artifact_id=issue_art.id,
                        link_type=link_type,
                        project_id=page_art.project_id,
                    )
                    db.add(link)
                    created += 1
                else:
                    updated += 1
                link.confidence = confidence
                link.confidence_factors = factors
        except IntegrityError:
            await db.rollback()
            updated += 1

    # Invalidate traceability caches if links were created/updated
    if created > 0 or updated > 0:
        await CacheInvalidator.on_artifact_link_change(project_id)

    return {"page_id": page_id, "created": created, "updated": updated, "suggestions": suggestions}
