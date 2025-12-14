from __future__ import annotations

import time
import logging
from typing import Optional, Dict, Any, List, Set, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.models import Artifact, ArtifactLink, Project, Task, ConfluencePage, User
from app.core.config import settings
from app.api.deps import get_current_user, ensure_project_access
from app.core.rate_limit import limiter
from app.services.confluence_service import confluence_service
from app.services.git_import_service import git_import_service
from app.core.database import AsyncSessionLocal
from app.utils import transactional_session, handle_api_error, count_with_filters, paginate_query, get_or_404, execute_with_lock

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-process cache for matrix (optional)
_matrix_cache: Dict[Tuple[Optional[int]], Tuple[float, Dict[str, Any]]] = {}


def _dag_types() -> Set[str]:
    return {"implements", "tests", "deploys", "derives_from"}


async def _would_create_cycle(db: AsyncSession, from_id: int, to_id: int, link_type: str) -> bool:
    """Detect cycle for DAG-enforced link types by exploring path to from_id starting from to_id."""
    if link_type not in _dag_types():
        return False
    seen: Set[int] = set()
    queue: List[int] = [to_id]
    while queue:
        cur = queue.pop(0)
        if cur == from_id:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        res = await db.execute(select(ArtifactLink.to_artifact_id).where(ArtifactLink.from_artifact_id == cur))
        for (next_id,) in res.all():
            if next_id not in seen:
                queue.append(next_id)
    return False


async def _link_exists(
    db: AsyncSession,
    from_id: int,
    to_id: int,
    link_type: str,
) -> Optional[ArtifactLink]:
    res = await db.execute(
        select(ArtifactLink).where(
            ArtifactLink.from_artifact_id == from_id,
            ArtifactLink.to_artifact_id == to_id,
            ArtifactLink.link_type == link_type,
        )
    )
    return res.scalar_one_or_none()


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
    current_user: User = Depends(get_current_user),
):
    if from_id == to_id:
        raise HTTPException(status_code=400, detail="from_id cannot equal to_id")

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    res = await db.execute(select(Artifact).where(Artifact.id.in_([from_id, to_id])))
    found = {a.id: a for a in res.scalars().all()}
    if from_id not in found or to_id not in found:
        raise HTTPException(status_code=404, detail="Artifact(s) not found")

    if await _would_create_cycle(db, from_id, to_id, link_type):
        raise HTTPException(status_code=409, detail="Link would create a cycle")

    try:
        async with db.begin():
            # Re-check existence under optional row lock
            sel = select(ArtifactLink).where(
                ArtifactLink.from_artifact_id == from_id,
                ArtifactLink.to_artifact_id == to_id,
                ArtifactLink.link_type == link_type,
            )
            link = (await execute_with_lock(db, sel)).scalar_one_or_none()
            if link is None:
                link = ArtifactLink(
                    from_artifact_id=from_id,
                    to_artifact_id=to_id,
                    link_type=link_type,
                    tenant_id=tenant_id,
                    project_id=project_id,
                )
                db.add(link)
            if confidence is not None:
                link.confidence = float(confidence)
            if confidence_factors is not None:
                link.confidence_factors = dict(confidence_factors)
        await db.refresh(link)
    except IntegrityError:
        await db.rollback()
        # Duplicate link under concurrent requests
        raise HTTPException(status_code=409, detail="Link already exists")
    return {"id": link.id, "status": "ok"}


@router.get("/task/{jira_key}/artifacts")
async def artifacts_for_task(
    jira_key: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Return artifact for task (jira_issue) and its immediate neighbors.
    Requires that backfill has been executed to project tasks as artifacts.
    """
    task_art = await get_or_404(
        db,
        select(Artifact).where(Artifact.type == "jira_issue", Artifact.external_id == jira_key),
        "Artifact for jira_key"
    )

    outgoing = await db.execute(
        select(ArtifactLink, Artifact).join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
        .where(ArtifactLink.from_artifact_id == task_art.id)
    )
    incoming = await db.execute(
        select(ArtifactLink, Artifact).join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
        .where(ArtifactLink.to_artifact_id == task_art.id)
    )
    out = [
        {
            "link_type": l.link_type,
            "confidence": l.confidence,
            "artifact": {
                "id": a.id,
                "type": a.type,
                "source": a.source,
                "external_id": a.external_id,
                "title": a.title,
                "status": a.status,
            },
        }
        for (l, a) in outgoing.all()
    ]
    inc = [
        {
            "link_type": l.link_type,
            "confidence": l.confidence,
            "artifact": {
                "id": a.id,
                "type": a.type,
                "source": a.source,
                "external_id": a.external_id,
                "title": a.title,
                "status": a.status,
            },
        }
        for (l, a) in incoming.all()
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
    current_user: User = Depends(get_current_user),
):
    """Return a simple BFS flow graph from a requirement artifact up to given depth."""
    depth = max(1, min(depth, 6))

    start = await get_or_404(db, select(Artifact).where(Artifact.id == artifact_id), "Artifact")

    if start.project_id is not None:
        await ensure_project_access(start.project_id, db, current_user)

    nodes: Dict[int, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    frontier: List[Tuple[int, int]] = [(start.id, 0)]
    seen: Set[int] = {start.id}

    while frontier:
        cur, d = frontier.pop(0)
        link_query = (
            select(ArtifactLink, Artifact)
            .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
            .where(ArtifactLink.from_artifact_id == cur)
        )
        if start.project_id is not None:
            link_query = link_query.where(ArtifactLink.project_id == start.project_id)

        res_links = await db.execute(link_query)
        for (link, artifact) in res_links.all():
            nodes.setdefault(
                artifact.id,
                {"id": artifact.id, "type": artifact.type, "title": artifact.title, "status": artifact.status},
            )
            edges.append({"from": cur, "to": artifact.id, "type": link.link_type, "confidence": link.confidence})
            if artifact.id not in seen and d + 1 < depth:
                seen.add(artifact.id)
                frontier.append((artifact.id, d + 1))

    nodes[start.id] = {"id": start.id, "type": start.type, "title": start.title, "status": start.status}
    return {"nodes": list(nodes.values()), "edges": edges}


@router.get("/matrix")
async def traceability_matrix(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a lightweight coverage-style matrix summary for a project."""
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    cache_key = (project_id,)
    if settings.ENABLE_MATRIX_CACHE:
        ttl = settings.MATRIX_CACHE_TTL_SECONDS
        cached = _matrix_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] < ttl:
            return cached[1]

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
            _matrix_cache[cache_key] = (time.time(), payload)
        return payload

    artifact_ids = [art.id for art in artifacts]
    link_stmt = select(ArtifactLink.from_artifact_id, ArtifactLink.link_type)
    link_stmt = link_stmt.where(ArtifactLink.from_artifact_id.in_(artifact_ids))
    res_links = await db.execute(link_stmt)
    raw_links = res_links.all()

    outgoing_link_totals: Dict[int, int] = {}
    outgoing_link_types: Dict[int, Dict[str, int]] = {}
    for from_id, link_type in raw_links:
        outgoing_link_totals[from_id] = outgoing_link_totals.get(from_id, 0) + 1
        type_bucket = outgoing_link_types.setdefault(from_id, {})
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
                "coverage_pct": 0.0,
                "avg_links_per_artifact": 0.0,
                "link_type_counts": {},
                "link_type_artifact_counts": {},
            },
        )
        stats["total"] += 1

        total_links = outgoing_link_totals.get(art.id, 0)
        stats["link_count"] += float(total_links)

        if total_links > 0:
            stats["linked"] += 1
            linked_artifact_count += 1
        else:
            stats["unlinked"] += 1

        per_link_type = outgoing_link_types.get(art.id, {})
        for link_type, count in per_link_type.items():
            type_counts = stats["link_type_counts"]
            type_counts[link_type] = type_counts.get(link_type, 0) + count

            artifact_count_map = stats["link_type_artifact_counts"]
            artifact_count_map[link_type] = artifact_count_map.get(link_type, 0) + 1

    for stats in per_type.values():
        total = stats["total"] or 1
        stats["coverage_pct"] = (stats["linked"] / total) * 100.0
        stats["avg_links_per_artifact"] = stats["link_count"] / total if total else 0.0
        stats["link_type_counts"] = dict(sorted(stats["link_type_counts"].items()))
        stats["link_type_artifact_counts"] = dict(sorted(stats["link_type_artifact_counts"].items()))

    payload = {
        "total": artifact_count,
        "by_type": by_type,
        "per_type": per_type,
        "coverage": {
            "linked_artifacts": linked_artifact_count,
            "coverage_pct": (linked_artifact_count / artifact_count * 100.0) if artifact_count else 0.0,
        },
    }

    if settings.ENABLE_MATRIX_CACHE:
        _matrix_cache[cache_key] = (time.time(), payload)

    return payload


@router.post("/backfill")
@limiter.limit("5/minute")
async def backfill_artifacts(
    request: Request,
    project_id: int,
    include_confluence: bool = True,
    include_git: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Project backfill: project tasks (jira_issue) and optionally local Confluence pages to artifacts."""
    project = await ensure_project_access(project_id, db, current_user)
    # Reset any auto-started transaction from earlier reads before the bulk write
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
                res = await db.execute(select(ConfluencePage))
                pages = res.scalars().all()
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
        # Concurrent backfill in another worker created duplicates — keep counts best-effort
        pass

    git_result = None
    if include_git:
        try:
            async with AsyncSessionLocal() as git_db:
                git_result = await git_import_service.sync_project(
                    git_db, project_id, include_commits=True, include_pull_requests=True
                )
        except Exception as exc:
            logger.error("Git import failed for project %s: %s", project_id, exc)
            git_result = {"error": str(exc)}

    payload = {"status": "ok", "created": created, "updated": updated}
    if git_result is not None:
        payload["git"] = git_result

    return JSONResponse(content=payload)


@router.post("/autolink/confluence/{page_id}")
async def autolink_confluence_page(
    page_id: str,
    project_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Parse a Confluence page, detect Jira keys, and create links."""
    if not settings.ENABLE_CONFLUENCE_AUTOLINK:
        raise HTTPException(status_code=400, detail="Feature ENABLE_CONFLUENCE_AUTOLINK is disabled")

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    page = confluence_service.get_page_by_id(page_id, expand='body.storage,version,metadata.labels')
    html = (page.get('body') or {}).get('storage', {}).get('value') or ''
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

    created = 0
    updated = 0
    suggestions: List[dict] = []

    for jc in key_contexts:
        ctx_lower = (jc.context or '').lower()
        link_type = 'implements' if any(k in ctx_lower for k in [
            'implement', 'requirement', 'acceptance criteria', 'design', 'solution'
        ]) else 'relates_to'
        base = 0.6
        if jc.in_link:
            base += 0.2
        if jc.in_header:
            base += 0.1
        if any(k in ctx_lower for k in ['requirement', 'acceptance', 'jira']):
            base += 0.05
        confidence = min(base, 0.95)
        factors = {
            'in_link': float(jc.in_link),
            'in_header': float(jc.in_header),
            'context_terms': {
                'requirement': float('requirement' in ctx_lower),
                'acceptance': float('acceptance' in ctx_lower),
            },
        }

        issue_stmt = select(Artifact).where(
            Artifact.type == 'jira_issue',
            Artifact.source == 'jira',
            Artifact.external_id == jc.key,
        )
        if project_id is not None:
            issue_stmt = issue_stmt.where(Artifact.project_id == project_id)
        res_issue = await db.execute(issue_stmt)
        issue_art = res_issue.scalar_one_or_none()

        if not page_art or not issue_art:
            suggestions.append({
                'jira_key': jc.key,
                'link_type': link_type,
                'confidence': confidence,
                'reason': 'artifact_missing',
                'page_artifact_exists': bool(page_art),
                'issue_artifact_exists': bool(issue_art),
            })
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
            # Duplicate under concurrency; treat as updated
            updated += 1
    return {"page_id": page_id, "created": created, "updated": updated, "suggestions": suggestions}


# ===== Traceability Rules Management =====

from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from app.schemas.traceability_rule import (
    TraceabilityRuleCreate,
    TraceabilityRuleUpdate,
    TraceabilityRuleResponse,
    TraceabilityRuleListResponse,
    TraceabilityRuleExecutionResponse,
    TraceabilityRuleExecutionListResponse,
)
from fastapi import Query


@router.get("/rules", response_model=TraceabilityRuleListResponse)
async def list_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    enabled: Optional[bool] = None,
    category: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all traceability rules with optional filters."""
    from sqlalchemy import and_, func as sql_func

    query = select(TraceabilityRule)
    filters = []
    if enabled is not None:
        filters.append(TraceabilityRule.enabled == enabled)
    if category:
        filters.append(TraceabilityRule.category == category)
    if project_id:
        filters.append(TraceabilityRule.project_id == project_id)

    if filters:
        query = query.where(and_(*filters))

    total = await count_with_filters(db, TraceabilityRule, filters)

    query = query.order_by(TraceabilityRule.created_at.desc())
    rules = await paginate_query(db, query, skip, limit)

    return TraceabilityRuleListResponse(
        total=total,
        items=[TraceabilityRuleResponse.from_db(rule) for rule in rules]
    )


@router.get("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific traceability rule by ID."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}"
    )

    return TraceabilityRuleResponse.from_db(rule)


@router.post("/rules", response_model=TraceabilityRuleResponse, status_code=201)
async def create_rule(
    rule_data: TraceabilityRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new traceability rule."""
    existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail=f"Rule with name '{rule_data.name}' already exists")

    new_rule = TraceabilityRule(
        name=rule_data.name,
        description=rule_data.description,
        flow_json=rule_data.flow_json.model_dump(),
        enabled=rule_data.enabled,
        category=rule_data.category,
        tags=rule_data.tags,
        project_id=rule_data.project_id,
        created_by_id=current_user.id,
    )

    async with transactional_session(db):
        db.add(new_rule)
    await db.refresh(new_rule)

    return TraceabilityRuleResponse.from_db(new_rule)


@router.put("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: TraceabilityRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}"
    )

    if rule_data.name and rule_data.name != rule.name:
        existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"Rule with name '{rule_data.name}' already exists")

    update_data = rule_data.model_dump(exclude_unset=True)
    if 'flow_json' in update_data and update_data['flow_json']:
        update_data['flow_json'] = update_data['flow_json']

    async with transactional_session(db):
        for field, value in update_data.items():
            setattr(rule, field, value)
    await db.refresh(rule)

    return TraceabilityRuleResponse.from_db(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}"
    )

    async with transactional_session(db):
        await db.delete(rule)


@router.get("/rules/{rule_id}/executions", response_model=TraceabilityRuleExecutionListResponse)
async def list_rule_executions(
    rule_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List execution history for a specific rule."""
    from sqlalchemy import func as sql_func

    await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}"
    )

    filters = [TraceabilityRuleExecution.rule_id == rule_id]
    total = await count_with_filters(db, TraceabilityRuleExecution, filters)

    query = select(TraceabilityRuleExecution).where(
        TraceabilityRuleExecution.rule_id == rule_id
    ).order_by(TraceabilityRuleExecution.started_at.desc())
    executions = await paginate_query(db, query, skip, limit)

    return TraceabilityRuleExecutionListResponse(
        total=total,
        items=[TraceabilityRuleExecutionResponse.from_orm(ex) for ex in executions]
    )


@router.post("/rules/{rule_id}/execute", response_model=dict)
async def execute_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Execute a traceability rule.

    Returns execution result with links created, errors, and warnings.
    """
    from app.services.rule_execution_engine import RuleExecutionEngine

    engine = RuleExecutionEngine(db)

    with handle_api_error(
        operation="execute_rule",
        status_code=500,
        context={"rule_id": rule_id},
        exception_map={ValueError: 400}
    ):
        result = engine.execute_rule(rule_id)
        return result


@router.get("/rules/executions", response_model=TraceabilityRuleExecutionListResponse)
async def get_all_rule_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[str] = Query(None, description="Filter by status: success, failed"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all traceability rule executions with pagination and filtering.
    """
    # Build query
    query = select(TraceabilityRuleExecution).order_by(TraceabilityRuleExecution.executed_at.desc())

    # Apply status filter
    if status:
        query = query.where(TraceabilityRuleExecution.status == status)

    # Get total count
    filters = [TraceabilityRuleExecution.status == status] if status else None
    total = await count_with_filters(db, TraceabilityRuleExecution, filters)

    # Apply pagination
    executions = await paginate_query(db, query, skip, limit)

    # Fetch rule names
    items = []
    for execution in executions:
        rule_result = await db.execute(
            select(TraceabilityRule).where(TraceabilityRule.id == execution.rule_id)
        )
        rule = rule_result.scalar_one_or_none()

        exec_data = TraceabilityRuleExecutionResponse.from_orm(execution).dict()
        exec_data['rule_name'] = rule.name if rule else f"Rule #{execution.rule_id}"
        items.append(exec_data)

    return TraceabilityRuleExecutionListResponse(
        total=total,
        items=items
    )



