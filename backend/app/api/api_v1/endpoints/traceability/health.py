"""Sync health monitoring and data consistency check endpoints."""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, exists
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Artifact, ArtifactLink, Project, User
from app.models.settings import IntegrationSetting
from app.models.project_repository import ProjectRepository
from app.api.deps import get_current_user, ensure_project_access
from .common import _dag_types

router = APIRouter()


def _suggest_link_action_by_type(artifact_type: str) -> str:
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
    return suggestions.get(artifact_type, "Review and create appropriate links")


def _calculate_consistency_health(issues: Dict[str, Any], is_filtered: bool) -> float:
    """
    Calculate a health score based on consistency issues found.

    Score is 0-1 where 1 is perfect consistency.
    """
    # Weight factors for different issue types
    weights = {
        "cycles": 0.4,  # Cycles are critical
        "broken_refs": 0.3,  # Broken refs are serious
        "duplicates": 0.1,  # Duplicates are moderate
        "orphans": 0.1,  # Orphans are informational
        "stale": 0.1,  # Stale is informational
    }

    # Penalty thresholds
    thresholds = {
        "cycles": 1,  # Any cycle is bad
        "broken_refs": 5,  # More than 5 broken refs is concerning
        "duplicates": 10,  # More than 10 duplicates is concerning
        "orphans": 100,  # More than 100 orphans is concerning
        "stale": 200,  # More than 200 stale is concerning
    }

    score = 1.0

    for issue_type, weight in weights.items():
        count = issues.get(issue_type, {}).get("count", 0)
        threshold = thresholds[issue_type]

        if count > 0:
            # Calculate penalty based on how much over threshold
            penalty = min(1.0, count / threshold) * weight
            score -= penalty

    return max(0.0, round(score, 2))


def _generate_consistency_recommendations(issues: Dict[str, Any]) -> List[Dict[str, str]]:
    """Generate actionable recommendations based on consistency issues found."""
    recommendations = []

    # Cycles are critical
    if issues["cycles"]["count"] > 0:
        recommendations.append(
            {
                "priority": "critical",
                "category": "cycles",
                "action": "Remove circular dependencies in DAG-enforced link types",
                "reason": f"Found {issues['cycles']['count']} cycle(s) that violate directed acyclic graph constraints",
                "fix": "Review and delete links that create cycles, or change link types to non-DAG types like 'relates_to'",
            }
        )

    # Broken refs are serious
    if issues["broken_refs"]["count"] > 0:
        recommendations.append(
            {
                "priority": "high",
                "category": "broken_refs",
                "action": "Clean up broken link references",
                "reason": f"Found {issues['broken_refs']['count']} link(s) pointing to non-existent artifacts",
                "fix": "Run the cleanup endpoint to remove broken links, or re-sync artifacts from source systems",
            }
        )

    # Duplicates
    if issues["duplicates"]["count"] > 0:
        recommendations.append(
            {
                "priority": "medium",
                "category": "duplicates",
                "action": "Remove duplicate links",
                "reason": f"Found {issues['duplicates']['count']} duplicate link(s)",
                "fix": "Run the cleanup endpoint with fix_duplicates=true to consolidate duplicates",
            }
        )

    # Orphans
    if issues["orphans"]["count"] > 50:
        recommendations.append(
            {
                "priority": "low",
                "category": "orphans",
                "action": "Review orphaned artifacts for potential links",
                "reason": f"Found {issues['orphans']['count']} artifact(s) with no traceability links",
                "fix": "Run auto-linking rules or generate link suggestions using TF-IDF similarity",
            }
        )
    elif issues["orphans"]["count"] > 0:
        recommendations.append(
            {
                "priority": "info",
                "category": "orphans",
                "action": "Consider linking orphaned artifacts",
                "reason": f"Found {issues['orphans']['count']} orphaned artifact(s)",
                "fix": "Review orphaned artifacts on the Orphaned Artifacts tab",
            }
        )

    # Stale artifacts
    if issues["stale"]["count"] > 100:
        recommendations.append(
            {
                "priority": "low",
                "category": "stale",
                "action": "Re-sync stale artifacts from source systems",
                "reason": f"Found {issues['stale']['count']} artifact(s) not updated in over 90 days",
                "fix": "Run backfill to refresh artifact data from Jira, Confluence, and Git",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "priority": "info",
                "category": "general",
                "action": "No issues found - traceability data is consistent",
                "reason": "All consistency checks passed",
                "fix": "Continue monitoring with periodic consistency checks",
            }
        )

    return recommendations


async def _detect_all_cycles(
    db: AsyncSession,
    project_id: Optional[int] = None,
    max_links: int = 10000,
) -> List[Dict[str, Any]]:
    """
    Detect cycles in DAG-enforced link types using DFS.

    Args:
        db: Database session
        project_id: Filter by project (strongly recommended for large systems)
        max_links: Maximum links to load (prevents memory exhaustion)

    Returns list of detected cycles with involved artifacts.
    """
    dag_types = _dag_types()

    # Get DAG-type links with safety limit
    link_query = select(
        ArtifactLink.from_artifact_id,
        ArtifactLink.to_artifact_id,
        ArtifactLink.link_type,
        ArtifactLink.id,
    ).where(ArtifactLink.link_type.in_(dag_types))

    if project_id is not None:
        link_query = link_query.where(ArtifactLink.project_id == project_id)

    # Apply safety limit to prevent memory exhaustion
    link_query = link_query.limit(max_links)

    result = await db.execute(link_query)
    links = result.all()

    if not links:
        return []

    # Build adjacency list
    graph: Dict[int, List[Tuple[int, str, int]]] = {}  # from_id -> [(to_id, link_type, link_id)]
    all_nodes: Set[int] = set()

    for row in links:
        from_id, to_id, link_type, link_id = row
        all_nodes.add(from_id)
        all_nodes.add(to_id)
        if from_id not in graph:
            graph[from_id] = []
        graph[from_id].append((to_id, link_type, link_id))

    # DFS to find cycles
    cycles_found: List[Dict[str, Any]] = []
    visited: Set[int] = set()
    rec_stack: Set[int] = set()
    path: List[int] = []

    def dfs(node: int) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        for to_id, link_type, link_id in graph.get(node, []):
            if to_id not in visited:
                if dfs(to_id):
                    return True
            elif to_id in rec_stack:
                # Found cycle
                cycle_start_idx = path.index(to_id)
                cycle_path = path[cycle_start_idx:] + [to_id]
                cycles_found.append(
                    {
                        "cycle_path": cycle_path,
                        "cycle_length": len(cycle_path) - 1,
                        "link_type": link_type,
                        "involves_artifacts": list(set(cycle_path)),
                    }
                )
                # Don't return True here to continue finding other cycles

        path.pop()
        rec_stack.remove(node)
        return False

    for node in all_nodes:
        if node not in visited:
            dfs(node)

    return cycles_found


@router.get("/sync-health")
async def get_sync_health(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get synchronization health status across all data sources.

    Returns:
    - Overall sync status
    - Per-source status (Jira, Confluence, Git)
    - Last sync times and artifact counts
    - Recent errors or warnings
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Build all queries first (no await yet)
    integrations_query = select(IntegrationSetting)

    source_counts_query = select(
        Artifact.source, sql_func.count(Artifact.id).label("count")
    ).group_by(Artifact.source)
    if project_id is not None:
        source_counts_query = source_counts_query.where(Artifact.project_id == project_id)

    projects_query = select(Project)
    if project_id is not None:
        projects_query = projects_query.where(Project.id == project_id)

    repos_query = select(ProjectRepository).options(selectinload(ProjectRepository.repository))
    if project_id is not None:
        repos_query = repos_query.where(ProjectRepository.project_id == project_id)

    # Execute all queries in parallel using asyncio.gather
    integrations_result, source_result, projects_result, repos_result = await asyncio.gather(
        db.execute(integrations_query),
        db.execute(source_counts_query),
        db.execute(projects_query),
        db.execute(repos_query),
    )

    # Process results
    integrations = {row.kind: row for row in integrations_result.scalars().all()}
    source_counts: Dict[str, int] = {
        row.source: int(getattr(row, "count", 0) or 0) for row in source_result.all()
    }
    projects = projects_result.scalars().all()
    repositories = repos_result.scalars().all()

    # Calculate last sync times per source
    last_syncs: Dict[str, Any] = {}
    project_sync_info = []

    for proj in projects:
        meta = proj.meta or {}
        last_sync = meta.get("last_sync_at")
        if last_sync:
            if "jira" not in last_syncs or last_sync > last_syncs.get("jira", ""):
                last_syncs["jira"] = last_sync

        project_sync_info.append(
            {
                "id": proj.id,
                "name": proj.name or proj.jira_key,
                "jira_key": proj.jira_key,
                "last_sync_at": last_sync,
                "issues_count": meta.get("issues_count", 0),
            }
        )

    repo_info = []
    for repo in repositories:
        repo_entity = getattr(repo, "repository", None)
        repo_info.append(
            {
                "id": repo.id,
                "project_id": repo.project_id,
                "name": repo_entity.repo_slug if repo_entity else None,
                "provider": repo_entity.provider if repo_entity else None,
                "url": (repo_entity.settings or {}).get("url") if repo_entity else None,
            }
        )

    # Build source status
    sources = []

    # Jira status
    jira_integration = integrations.get("jira")
    sources.append(
        {
            "source": "jira",
            "label": "Jira",
            "status": "connected"
            if jira_integration and jira_integration.base_url
            else "not_configured",
            "base_url": jira_integration.base_url if jira_integration else None,
            "artifact_count": source_counts.get("jira", 0),
            "last_sync": last_syncs.get("jira"),
            "updated_at": jira_integration.updated_at.isoformat()
            if jira_integration and jira_integration.updated_at
            else None,
        }
    )

    # Confluence status
    confluence_integration = integrations.get("confluence")
    confluence_page_count = source_counts.get("confluence", 0)
    sources.append(
        {
            "source": "confluence",
            "label": "Confluence",
            "status": "connected"
            if confluence_integration and confluence_integration.base_url
            else "not_configured",
            "base_url": confluence_integration.base_url if confluence_integration else None,
            "artifact_count": confluence_page_count,
            "last_sync": None,  # Confluence doesn't have centralized sync tracking
            "updated_at": confluence_integration.updated_at.isoformat()
            if confluence_integration and confluence_integration.updated_at
            else None,
        }
    )

    # Git status
    git_artifact_count = int(source_counts.get("github", 0)) + int(source_counts.get("gitlab", 0))
    sources.append(
        {
            "source": "git",
            "label": "Git Repositories",
            "status": "connected" if repositories else "not_configured",
            "repository_count": len(repositories),
            "artifact_count": git_artifact_count,
            "last_sync": None,
            "repositories": repo_info[:10],  # Limit to first 10
        }
    )

    # Calculate overall health
    total_artifacts = sum(source_counts.values())
    configured_sources = sum(1 for s in sources if s["status"] == "connected")
    total_sources = len(sources)

    # Health score: weighted by artifact coverage and source connectivity
    health_score = 0.0
    if total_sources > 0:
        connectivity_score = configured_sources / total_sources * 0.4
        # Artifact coverage: penalize if any major source has 0 artifacts
        positive_sources = sum(1 for s in sources if int(s.get("artifact_count") or 0) > 0)
        artifact_coverage = positive_sources / total_sources * 0.6
        health_score = connectivity_score + artifact_coverage

    health_status = (
        "healthy" if health_score >= 0.7 else ("warning" if health_score >= 0.4 else "critical")
    )

    return {
        "health": {
            "status": health_status,
            "score": round(health_score, 2),
            "connected_sources": configured_sources,
            "total_sources": total_sources,
        },
        "summary": {
            "total_artifacts": total_artifacts,
            "total_links": 0,  # Will be calculated below
            "projects_count": len(projects),
            "repositories_count": len(repositories),
        },
        "sources": sources,
        "projects": project_sync_info[:20],  # Limit to first 20
    }


@router.get("/sync-health/detailed")
async def get_detailed_sync_health(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed sync health for a specific project.

    Returns more granular data including:
    - Per-artifact-type breakdown
    - Link coverage by source
    - Recent sync history (if available)
    """
    project = await ensure_project_access(project_id, db, current_user)

    # Build all queries first (parallel execution)
    type_source_query = (
        select(Artifact.type, Artifact.source, sql_func.count(Artifact.id).label("count"))
        .where(Artifact.project_id == project_id)
        .group_by(Artifact.type, Artifact.source)
    )

    link_query = (
        select(ArtifactLink.link_type, sql_func.count(ArtifactLink.id).label("count"))
        .where(ArtifactLink.project_id == project_id)
        .group_by(ArtifactLink.link_type)
    )

    repos_query = select(ProjectRepository).where(ProjectRepository.project_id == project_id)

    has_link = exists(
        select(ArtifactLink.id).where(
            (ArtifactLink.from_artifact_id == Artifact.id)
            | (ArtifactLink.to_artifact_id == Artifact.id)
        )
    )
    orphan_count_query = select(sql_func.count(Artifact.id)).where(
        Artifact.project_id == project_id, ~has_link
    )

    # Execute all queries in parallel
    type_source_result, link_result, repos_result, orphan_result = await asyncio.gather(
        db.execute(type_source_query),
        db.execute(link_query),
        db.execute(repos_query),
        db.execute(orphan_count_query),
    )

    # Process results
    type_source_counts = type_source_result.all()
    links_by_type = {row.link_type: int(getattr(row, "count", 0) or 0) for row in link_result.all()}
    repositories = repos_result.scalars().all()
    orphan_count = orphan_result.scalar() or 0

    # Build breakdown
    by_type: Dict[str, Dict[str, Any]] = {}
    by_source: Dict[str, Dict[str, Any]] = {}
    for row in type_source_counts:
        art_type, source, count = row.type, row.source, int(getattr(row, "count", 0) or 0)
        if art_type not in by_type:
            by_type[art_type] = {"total": 0, "by_source": {}}
        by_type[art_type]["total"] += count
        by_type[art_type]["by_source"][source] = count

        if source not in by_source:
            by_source[source] = {"total": 0, "by_type": {}}
        by_source[source]["total"] += count
        by_source[source]["by_type"][art_type] = count

    repo_info = []
    for r in repositories:
        repo_entity = getattr(r, "repository", None)
        repo_info.append(
            {
                "id": r.id,
                "name": repo_entity.repo_slug if repo_entity else None,
                "provider": repo_entity.provider if repo_entity else None,
                "url": (repo_entity.settings or {}).get("url") if repo_entity else None,
            }
        )

    # Project metadata
    meta = project.meta or {}

    return {
        "project": {
            "id": project.id,
            "name": project.name or project.jira_key,
            "jira_key": project.jira_key,
            "last_sync_at": meta.get("last_sync_at"),
            "issues_count": meta.get("issues_count", 0),
        },
        "artifacts": {
            "by_type": by_type,
            "by_source": by_source,
            "total": sum(int(by_source[s]["total"]) for s in by_source),
        },
        "links": {
            "by_type": links_by_type,
            "total": sum(links_by_type.values()),
        },
        "coverage": {
            "orphaned_artifacts": orphan_count,
            "linked_artifacts": sum(by_source[s]["total"] for s in by_source) - orphan_count,
        },
        "repositories": repo_info,
    }


@router.get("/consistency-check")
async def run_consistency_check(
    project_id: Optional[int] = None,
    check_orphans: bool = Query(True, description="Check for orphaned artifacts"),
    check_cycles: bool = Query(True, description="Check for circular dependencies"),
    check_duplicates: bool = Query(True, description="Check for duplicate links"),
    check_broken_refs: bool = Query(True, description="Check for broken references"),
    check_stale: bool = Query(True, description="Check for stale artifacts"),
    stale_days: int = Query(90, ge=7, le=365, description="Days threshold for stale artifacts"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run comprehensive data consistency checks on the traceability graph.

    Returns issues found across multiple categories:
    - Orphaned artifacts (no links)
    - Circular dependencies (cycles in DAG types)
    - Duplicate links (same from/to/type)
    - Broken references (links to non-existent artifacts)
    - Stale artifacts (not updated for N days)
    """

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    issues: Dict[str, Any] = {
        "orphans": {"count": 0, "items": []},
        "cycles": {"count": 0, "items": []},
        "duplicates": {"count": 0, "items": []},
        "broken_refs": {"count": 0, "items": []},
        "stale": {"count": 0, "items": []},
    }

    total_issues = 0

    # 1. Orphaned artifacts check
    if check_orphans:
        has_outgoing = exists(
            select(ArtifactLink.id).where(ArtifactLink.from_artifact_id == Artifact.id)
        )
        has_incoming = exists(
            select(ArtifactLink.id).where(ArtifactLink.to_artifact_id == Artifact.id)
        )

        orphan_query = select(
            Artifact.id, Artifact.type, Artifact.external_id, Artifact.title
        ).where(~has_outgoing, ~has_incoming)
        if project_id is not None:
            orphan_query = orphan_query.where(Artifact.project_id == project_id)

        orphan_query = orphan_query.limit(100)
        orphan_result = await db.execute(orphan_query)
        orphans = orphan_result.all()

        # Get total count
        count_query = select(sql_func.count(Artifact.id)).where(~has_outgoing, ~has_incoming)
        if project_id is not None:
            count_query = count_query.where(Artifact.project_id == project_id)
        count_result = await db.execute(count_query)
        orphan_count = count_result.scalar() or 0

        issues["orphans"]["count"] = orphan_count
        issues["orphans"]["items"] = [
            {
                "id": row.id,
                "type": row.type,
                "external_id": row.external_id,
                "title": row.title,
                "suggestion": _suggest_link_action_by_type(row.type),
            }
            for row in orphans
        ]
        total_issues += orphan_count

    # 2. Cycle detection for DAG-enforced link types
    if check_cycles:
        cycles_found = await _detect_all_cycles(db, project_id)
        issues["cycles"]["count"] = len(cycles_found)
        issues["cycles"]["items"] = cycles_found[:20]  # Limit returned items
        total_issues += len(cycles_found)

    # 3. Duplicate links check
    if check_duplicates:
        dup_query = (
            select(
                ArtifactLink.from_artifact_id,
                ArtifactLink.to_artifact_id,
                ArtifactLink.link_type,
                sql_func.count(ArtifactLink.id).label("dup_count"),
            )
            .group_by(
                ArtifactLink.from_artifact_id, ArtifactLink.to_artifact_id, ArtifactLink.link_type
            )
            .having(sql_func.count(ArtifactLink.id) > 1)
        )

        if project_id is not None:
            dup_query = dup_query.where(ArtifactLink.project_id == project_id)

        dup_result = await db.execute(dup_query)
        duplicates = dup_result.all()

        issues["duplicates"]["count"] = len(duplicates)
        issues["duplicates"]["items"] = [
            {
                "from_artifact_id": row.from_artifact_id,
                "to_artifact_id": row.to_artifact_id,
                "link_type": row.link_type,
                "duplicate_count": row.dup_count,
            }
            for row in duplicates[:50]
        ]
        total_issues += len(duplicates)

    # 4. Broken references check (links pointing to non-existent artifacts)
    if check_broken_refs:
        # Check for links where from_artifact doesn't exist
        from_broken = select(
            ArtifactLink.id,
            ArtifactLink.from_artifact_id,
            ArtifactLink.to_artifact_id,
            ArtifactLink.link_type,
        ).where(~exists(select(Artifact.id).where(Artifact.id == ArtifactLink.from_artifact_id)))
        if project_id is not None:
            from_broken = from_broken.where(ArtifactLink.project_id == project_id)

        # Check for links where to_artifact doesn't exist
        to_broken = select(
            ArtifactLink.id,
            ArtifactLink.from_artifact_id,
            ArtifactLink.to_artifact_id,
            ArtifactLink.link_type,
        ).where(~exists(select(Artifact.id).where(Artifact.id == ArtifactLink.to_artifact_id)))
        if project_id is not None:
            to_broken = to_broken.where(ArtifactLink.project_id == project_id)

        from_result = await db.execute(from_broken)
        to_result = await db.execute(to_broken)

        broken_from = [
            {
                "link_id": row.id,
                "from_artifact_id": row.from_artifact_id,
                "to_artifact_id": row.to_artifact_id,
                "link_type": row.link_type,
                "issue": "from_artifact_missing",
            }
            for row in from_result.all()
        ]
        broken_to = [
            {
                "link_id": row.id,
                "from_artifact_id": row.from_artifact_id,
                "to_artifact_id": row.to_artifact_id,
                "link_type": row.link_type,
                "issue": "to_artifact_missing",
            }
            for row in to_result.all()
        ]

        all_broken = broken_from + broken_to
        issues["broken_refs"]["count"] = len(all_broken)
        issues["broken_refs"]["items"] = all_broken[:50]
        total_issues += len(all_broken)

    # 5. Stale artifacts check (not updated recently)
    if check_stale:
        stale_threshold = datetime.utcnow() - timedelta(days=stale_days)

        stale_query = select(
            Artifact.id, Artifact.type, Artifact.external_id, Artifact.title, Artifact.updated_at
        ).where(Artifact.updated_at < stale_threshold)
        if project_id is not None:
            stale_query = stale_query.where(Artifact.project_id == project_id)

        stale_query = stale_query.order_by(Artifact.updated_at.asc()).limit(100)
        stale_result = await db.execute(stale_query)
        stale_artifacts = stale_result.all()

        # Get total count
        stale_count_query = select(sql_func.count(Artifact.id)).where(
            Artifact.updated_at < stale_threshold
        )
        if project_id is not None:
            stale_count_query = stale_count_query.where(Artifact.project_id == project_id)
        stale_count_result = await db.execute(stale_count_query)
        stale_count = stale_count_result.scalar() or 0

        issues["stale"]["count"] = stale_count
        issues["stale"]["items"] = [
            {
                "id": row.id,
                "type": row.type,
                "external_id": row.external_id,
                "title": row.title,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "days_since_update": (datetime.utcnow() - row.updated_at).days
                if row.updated_at
                else None,
            }
            for row in stale_artifacts
        ]
        total_issues += stale_count

    # Calculate overall health score
    health_score = _calculate_consistency_health(issues, project_id is not None)

    return {
        "project_id": project_id,
        "checked_at": datetime.utcnow().isoformat(),
        "total_issues": total_issues,
        "health_score": health_score,
        "status": "healthy"
        if health_score >= 0.9
        else ("warning" if health_score >= 0.7 else "critical"),
        "issues": issues,
        "recommendations": _generate_consistency_recommendations(issues),
    }


@router.post("/consistency-check/fix")
async def fix_consistency_issues(
    project_id: Optional[int] = None,
    fix_broken_refs: bool = Query(True, description="Remove links with missing artifacts"),
    fix_duplicates: bool = Query(
        True, description="Remove duplicate links (keeps highest confidence)"
    ),
    dry_run: bool = Query(True, description="Preview changes without applying them"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fix common consistency issues automatically.

    By default runs in dry_run mode to preview changes.
    Set dry_run=False to actually apply fixes.

    Returns:
    - fixed: Number of issues fixed
    - preview: List of fixes that would be applied (in dry_run mode)
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    fixes_preview: List[Dict[str, Any]] = []
    fixes: Dict[str, Any] = {
        "broken_refs_removed": 0,
        "duplicates_removed": 0,
        "preview": fixes_preview,
    }

    # 1. Fix broken references
    if fix_broken_refs:
        # Find links with missing from_artifact
        from_broken_query = select(ArtifactLink).where(
            ~exists(select(Artifact.id).where(Artifact.id == ArtifactLink.from_artifact_id))
        )
        if project_id is not None:
            from_broken_query = from_broken_query.where(ArtifactLink.project_id == project_id)

        from_result = await db.execute(from_broken_query)
        broken_from = from_result.scalars().all()

        # Find links with missing to_artifact
        to_broken_query = select(ArtifactLink).where(
            ~exists(select(Artifact.id).where(Artifact.id == ArtifactLink.to_artifact_id))
        )
        if project_id is not None:
            to_broken_query = to_broken_query.where(ArtifactLink.project_id == project_id)

        to_result = await db.execute(to_broken_query)
        broken_to = to_result.scalars().all()

        broken_links = list(broken_from) + list(broken_to)
        seen: Set[int] = set()
        all_broken: List[ArtifactLink] = []
        for link in broken_links:
            if link.id not in seen:
                seen.add(link.id)
                all_broken.append(link)

        for link in all_broken:
            if dry_run:
                fixes["preview"].append(
                    {
                        "action": "delete_link",
                        "reason": "broken_reference",
                        "link_id": link.id,
                        "from_artifact_id": link.from_artifact_id,
                        "to_artifact_id": link.to_artifact_id,
                    }
                )
            else:
                await db.delete(link)
                fixes["broken_refs_removed"] += 1

    # 2. Fix duplicate links
    if fix_duplicates:
        # Find duplicates
        dup_query = (
            select(
                ArtifactLink.from_artifact_id,
                ArtifactLink.to_artifact_id,
                ArtifactLink.link_type,
            )
            .group_by(
                ArtifactLink.from_artifact_id, ArtifactLink.to_artifact_id, ArtifactLink.link_type
            )
            .having(sql_func.count(ArtifactLink.id) > 1)
        )

        if project_id is not None:
            dup_query = dup_query.where(ArtifactLink.project_id == project_id)

        dup_result = await db.execute(dup_query)
        duplicate_groups = dup_result.all()

        for group in duplicate_groups:
            from_id, to_id, link_type = group

            # Get all links in this duplicate group
            links_query = (
                select(ArtifactLink)
                .where(
                    ArtifactLink.from_artifact_id == from_id,
                    ArtifactLink.to_artifact_id == to_id,
                    ArtifactLink.link_type == link_type,
                )
                .order_by(
                    # Keep the one with highest confidence, or most recent
                    ArtifactLink.confidence.desc().nullslast(),
                    ArtifactLink.created_at.desc(),
                )
            )
            links_result = await db.execute(links_query)
            duplicate_links = links_result.scalars().all()

            # Keep the first (best) one, remove the rest
            for link in duplicate_links[1:]:
                if dry_run:
                    fixes["preview"].append(
                        {
                            "action": "delete_link",
                            "reason": "duplicate",
                            "link_id": link.id,
                            "from_artifact_id": link.from_artifact_id,
                            "to_artifact_id": link.to_artifact_id,
                            "link_type": link.link_type,
                            "kept_link_id": duplicate_links[0].id,
                        }
                    )
                else:
                    await db.delete(link)
                    fixes["duplicates_removed"] += 1

    if not dry_run:
        await db.commit()

    return {
        "dry_run": dry_run,
        "project_id": project_id,
        "fixes_applied": fixes["broken_refs_removed"] + fixes["duplicates_removed"]
        if not dry_run
        else 0,
        "broken_refs_removed": fixes["broken_refs_removed"],
        "duplicates_removed": fixes["duplicates_removed"],
        "preview": fixes["preview"] if dry_run else [],
        "message": (
            f"Preview: {len(fixes['preview'])} fixes would be applied"
            if dry_run
            else f"Applied {fixes['broken_refs_removed'] + fixes['duplicates_removed']} fixes"
        ),
    }


@router.get("/consistency-check/cycles")
async def detect_cycles_detailed(
    project_id: Optional[int] = None,
    link_type: Optional[str] = Query(None, description="Filter by link type"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed cycle detection analysis.

    Returns all cycles found with full artifact information.
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    cycles = await _detect_all_cycles(db, project_id)

    if link_type:
        cycles = [c for c in cycles if c["link_type"] == link_type]

    if not cycles:
        return {
            "project_id": project_id,
            "cycles_found": 0,
            "cycles": [],
            "status": "healthy",
            "message": "No cycles detected in DAG-enforced link types",
        }

    # Get artifact details for all involved nodes
    all_artifact_ids: Set[int] = set()
    for cycle in cycles:
        all_artifact_ids.update(cycle["involves_artifacts"])

    artifacts_result = await db.execute(select(Artifact).where(Artifact.id.in_(all_artifact_ids)))
    artifacts = {a.id: a for a in artifacts_result.scalars().all()}

    # Enrich cycles with artifact details
    enriched_cycles = []
    for cycle in cycles:
        enriched_path = []
        for art_id in cycle["cycle_path"]:
            art = artifacts.get(art_id)
            if art:
                enriched_path.append(
                    {
                        "id": art.id,
                        "type": art.type,
                        "external_id": art.external_id,
                        "display_key": art.display_key or art.external_id,
                        "title": art.title,
                    }
                )
            else:
                enriched_path.append({"id": art_id, "missing": True})

        enriched_cycles.append(
            {
                "cycle_path": enriched_path,
                "cycle_length": cycle["cycle_length"],
                "link_type": cycle["link_type"],
                "severity": "critical" if cycle["cycle_length"] > 3 else "high",
            }
        )

    return {
        "project_id": project_id,
        "cycles_found": len(enriched_cycles),
        "cycles": enriched_cycles,
        "status": "critical" if enriched_cycles else "healthy",
        "message": f"Found {len(enriched_cycles)} cycle(s) in DAG-enforced link types",
        "dag_types": list(_dag_types()),
    }
