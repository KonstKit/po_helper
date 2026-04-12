"""Sync health monitoring and data consistency check endpoints."""

from __future__ import annotations

import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sql_func, exists
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.crypto import decrypt_str
from app.core.database import get_db
from app.models import Artifact, ArtifactLink, Project, User, Permissions
from app.models.settings import IntegrationSetting
from app.models.project_repository import ProjectRepository
from app.api.deps import ensure_project_access, require_permission
from app.services.integration_config import get_connector_overrides, get_connector_overrides_map
from app.services.jira import JiraService
from app.services.confluence_service import ConfluenceService
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
                "fix": "Run source sync or traceability repair to refresh artifact data from Jira, Confluence, and Git",
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


def _isoformat(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _safe_decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        decrypted = decrypt_str(value)
    except Exception:
        return None
    return decrypted or None


def _project_meta(project: Project) -> Dict[str, Any]:
    meta = project.meta
    return meta if isinstance(meta, dict) else {}


def _project_last_sync(project: Project) -> Optional[str]:
    meta = _project_meta(project)
    raw = meta.get("last_sync_at")
    return str(raw) if raw else None


def _compute_project_health_status(
    *,
    last_sync: Optional[str],
    artifact_count: int,
    source_statuses: Optional[List[str]] = None,
) -> str:
    if last_sync:
        try:
            last_sync_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
            age_days = (datetime.utcnow() - last_sync_dt.replace(tzinfo=None)).days
            if age_days > 7:
                return "stale"
        except ValueError:
            pass

    statuses = set(source_statuses or [])
    if "degraded" in statuses and artifact_count == 0:
        return "critical"
    if artifact_count == 0:
        return "warning"
    if "degraded" in statuses:
        return "warning"
    if "reachable" in statuses:
        return "healthy"
    return "unknown"


def _compute_overall_health(reachable_sources: int, total_sources: int, total_artifacts: int) -> tuple[str, float]:
    if total_sources <= 0:
        return "critical", 0.0

    connectivity = reachable_sources / total_sources
    artifact_bonus = 1.0 if total_artifacts > 0 else 0.0
    score = round(((connectivity * 0.7) + (artifact_bonus * 0.3)) * 100, 1)

    if score >= 80:
        return "healthy", score
    if score >= 45:
        return "warning", score
    return "critical", score


async def _build_jira_source_health(
    db: AsyncSession,
    *,
    project_id: Optional[int],
    integration: Optional[IntegrationSetting],
    artifact_count: int,
    last_sync: Optional[str],
    checked_at: str,
) -> Dict[str, Any]:
    overrides = await get_connector_overrides(db, project_id, "jira")
    if overrides and not overrides.enabled:
        return {
            "source": "jira",
            "label": "Jira",
            "status": "not_configured",
            "effective_connector_source": "project_override",
            "artifact_count": artifact_count,
            "last_sync": last_sync,
            "checked_at": checked_at,
            "error": "Connector disabled for this project",
        }

    base_url = (
        str(overrides.settings.get("base_url"))
        if overrides and overrides.settings.get("base_url")
        else (integration.base_url if integration and integration.base_url else settings.JIRA_BASE_URL)
    )
    token = (
        str(overrides.settings.get("api_token"))
        if overrides and overrides.settings.get("api_token")
        else (_safe_decrypt(integration.api_token) if integration else settings.JIRA_API_TOKEN)
    )
    email = (
        str(overrides.settings.get("email"))
        if overrides and overrides.settings.get("email")
        else (integration.email if integration and integration.email else settings.JIRA_EMAIL)
    )
    email = None if getattr(settings, "JIRA_FORCE_PAT", True) else (email or None)

    effective_source = "project_override" if overrides else "global"
    if not base_url or not token:
        return {
            "source": "jira",
            "label": "Jira",
            "status": "not_configured",
            "effective_connector_source": effective_source if overrides else "none",
            "artifact_count": artifact_count,
            "last_sync": last_sync,
            "checked_at": checked_at,
            "error": None,
        }

    try:
        client = JiraService()
        client.connect(base_url, email, token)
        client.validate()
        status = "reachable"
        error = None
    except Exception as exc:
        status = "degraded"
        error = str(exc)

    return {
        "source": "jira",
        "label": "Jira",
        "status": status,
        "effective_connector_source": effective_source,
        "artifact_count": artifact_count,
        "last_sync": last_sync,
        "checked_at": checked_at,
        "error": error,
        "base_url": base_url,
    }


async def _build_confluence_source_health(
    db: AsyncSession,
    *,
    project_id: Optional[int],
    integration: Optional[IntegrationSetting],
    artifact_count: int,
    last_sync: Optional[str],
    checked_at: str,
) -> Dict[str, Any]:
    overrides = await get_connector_overrides(db, project_id, "confluence")
    if overrides and not overrides.enabled:
        return {
            "source": "confluence",
            "label": "Confluence",
            "status": "not_configured",
            "effective_connector_source": "project_override",
            "artifact_count": artifact_count,
            "last_sync": last_sync,
            "checked_at": checked_at,
            "error": "Connector disabled for this project",
        }

    base_url = (
        str(overrides.settings.get("base_url"))
        if overrides and overrides.settings.get("base_url")
        else (
            integration.base_url if integration and integration.base_url else settings.CONFLUENCE_BASE_URL
        )
    )
    token = (
        str(overrides.settings.get("api_token"))
        if overrides and overrides.settings.get("api_token")
        else (_safe_decrypt(integration.api_token) if integration else settings.CONFLUENCE_API_TOKEN)
    )
    email = (
        str(overrides.settings.get("email"))
        if overrides and overrides.settings.get("email")
        else (integration.email if integration and integration.email else settings.CONFLUENCE_EMAIL)
    )
    effective_source = "project_override" if overrides else "global"
    if not base_url or not token:
        return {
            "source": "confluence",
            "label": "Confluence",
            "status": "not_configured",
            "effective_connector_source": effective_source if overrides else "none",
            "artifact_count": artifact_count,
            "last_sync": last_sync,
            "checked_at": checked_at,
            "error": None,
        }

    try:
        client = ConfluenceService()
        client.connect(base_url, email or None, token)
        client.validate()
        status = "reachable"
        error = None
    except Exception as exc:
        status = "degraded"
        error = str(exc)

    return {
        "source": "confluence",
        "label": "Confluence",
        "status": status,
        "effective_connector_source": effective_source,
        "artifact_count": artifact_count,
        "last_sync": last_sync,
        "checked_at": checked_at,
        "error": error,
        "base_url": base_url,
    }


async def _build_git_source_health(
    db: AsyncSession,
    *,
    project_id: Optional[int],
    integrations: Dict[str, IntegrationSetting],
    repositories: List[ProjectRepository],
    artifact_count: int,
    checked_at: str,
) -> Dict[str, Any]:
    if not repositories:
        return {
            "source": "git",
            "label": "Git Repositories",
            "status": "not_configured",
            "effective_connector_source": "none",
            "artifact_count": artifact_count,
            "last_sync": None,
            "checked_at": checked_at,
            "error": None,
            "repository_count": 0,
        }

    providers = {(getattr(repo.repository, "provider", None) or "").lower() for repo in repositories}
    providers.discard("")
    overrides = await get_connector_overrides_map(db, project_id, providers)

    missing_providers: List[str] = []
    for provider in sorted(providers):
        override = overrides.get(provider)
        if override and not override.enabled:
            missing_providers.append(provider)
            continue

        integration = integrations.get(provider)
        token = None
        if override and (override.settings.get("api_token") or override.settings.get("token")):
            token = str(override.settings.get("api_token") or override.settings.get("token"))
        elif integration:
            token = _safe_decrypt(integration.api_token)
        if not token:
            missing_providers.append(provider)

    status = "reachable" if not missing_providers else "degraded"
    error = None
    if missing_providers:
        error = f"Missing active provider credentials: {', '.join(sorted(missing_providers))}"

    return {
        "source": "git",
        "label": "Git Repositories",
        "status": status,
        "effective_connector_source": "repository_link",
        "artifact_count": artifact_count,
        "last_sync": None,
        "checked_at": checked_at,
        "error": error,
        "repository_count": len(repositories),
    }


@router.get("/sync-health")
async def get_sync_health(
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get canonical synchronization health across sources."""
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")

    selected_project: Optional[Project] = None
    if project_id is not None:
        selected_project = await ensure_project_access(project_id, db, current_user)

    integrations_result = await db.execute(select(IntegrationSetting))
    integrations = {row.kind: row for row in integrations_result.scalars().all()}

    source_counts_query = select(
        Artifact.source,
        sql_func.count(Artifact.id).label("count"),
    ).group_by(Artifact.source)
    if project_id is not None:
        source_counts_query = source_counts_query.where(Artifact.project_id == project_id)
    source_counts_result = await db.execute(source_counts_query)
    source_counts: Dict[str, int] = {
        row.source: int(getattr(row, "count", 0) or 0)
        for row in source_counts_result.all()
    }

    project_counts_query = (
        select(Artifact.project_id, sql_func.count(Artifact.id).label("count"))
        .where(Artifact.project_id.is_not(None))
        .group_by(Artifact.project_id)
    )
    if project_id is not None:
        project_counts_query = project_counts_query.where(Artifact.project_id == project_id)
    project_counts_result = await db.execute(project_counts_query)
    project_artifact_counts = {
        int(row.project_id): int(getattr(row, "count", 0) or 0)
        for row in project_counts_result.all()
        if row.project_id is not None
    }

    projects_query = select(Project).order_by(Project.id.asc())
    if project_id is not None:
        projects_query = projects_query.where(Project.id == project_id)
    projects_result = await db.execute(projects_query)
    projects = projects_result.scalars().all()

    repos_query = select(ProjectRepository).options(selectinload(ProjectRepository.repository))
    if project_id is not None:
        repos_query = repos_query.where(ProjectRepository.project_id == project_id)
    repositories_result = await db.execute(repos_query)
    repositories = repositories_result.scalars().all()

    checked_at = datetime.utcnow().isoformat()
    jira_last_sync = _project_last_sync(selected_project) if selected_project else None
    if jira_last_sync is None:
        jira_last_sync = next((value for value in (_project_last_sync(project) for project in projects) if value), None)

    confluence_last_sync = None
    git_artifact_count = int(source_counts.get("github", 0)) + int(source_counts.get("gitlab", 0))

    sources = [
        await _build_jira_source_health(
            db,
            project_id=project_id,
            integration=integrations.get("jira"),
            artifact_count=source_counts.get("jira", 0),
            last_sync=jira_last_sync,
            checked_at=checked_at,
        ),
        await _build_confluence_source_health(
            db,
            project_id=project_id,
            integration=integrations.get("confluence"),
            artifact_count=source_counts.get("confluence", 0),
            last_sync=confluence_last_sync,
            checked_at=checked_at,
        ),
        await _build_git_source_health(
            db,
            project_id=project_id,
            integrations=integrations,
            repositories=repositories,
            artifact_count=git_artifact_count,
            checked_at=checked_at,
        ),
    ]

    total_artifacts = sum(source_counts.values())
    reachable_sources = sum(1 for source in sources if source["status"] == "reachable")
    overall_status, overall_score = _compute_overall_health(
        reachable_sources, len(sources), total_artifacts
    )

    project_rows = []
    for project in projects:
        last_sync = _project_last_sync(project)
        artifact_count = int(project_artifact_counts.get(project.id, 0))
        project_rows.append(
            {
                "project_id": project.id,
                "project_name": project.name or project.jira_key,
                "jira_key": project.jira_key,
                "last_sync": last_sync,
                "artifact_count": artifact_count,
                "health_status": _compute_project_health_status(
                    last_sync=last_sync,
                    artifact_count=artifact_count,
                    source_statuses=[source["status"] for source in sources],
                ),
            }
        )

    return {
        "health": {"status": overall_status, "score": overall_score},
        "summary": {
            "total_sources": len(sources),
            "reachable_sources": reachable_sources,
            "total_artifacts": total_artifacts,
            "last_sync": jira_last_sync,
            "checked_at": checked_at,
        },
        "sources": sources,
        "projects": project_rows[:20],
    }


@router.get("/sync-health/detailed")
async def get_detailed_sync_health(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get canonical sync-health details for one project."""
    project = await ensure_project_access(project_id, db, current_user)

    type_source_query = (
        select(Artifact.type, Artifact.source, sql_func.count(Artifact.id).label("count"))
        .where(Artifact.project_id == project_id)
        .group_by(Artifact.type, Artifact.source)
    )
    repos_query = (
        select(ProjectRepository)
        .options(selectinload(ProjectRepository.repository))
        .where(ProjectRepository.project_id == project_id)
    )
    has_link = exists(
        select(ArtifactLink.id).where(
            (ArtifactLink.from_artifact_id == Artifact.id) | (ArtifactLink.to_artifact_id == Artifact.id)
        )
    )
    orphan_count_query = select(sql_func.count(Artifact.id)).where(
        Artifact.project_id == project_id,
        ~has_link,
    )
    integrations_result = await db.execute(select(IntegrationSetting))
    integrations = {row.kind: row for row in integrations_result.scalars().all()}
    type_source_result = await db.execute(type_source_query)
    repos_result = await db.execute(repos_query)
    orphan_result = await db.execute(orphan_count_query)

    repositories = repos_result.scalars().all()
    orphan_count = int(orphan_result.scalar() or 0)
    by_type: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    for row in type_source_result.all():
        art_type = str(row.type)
        source = str(row.source)
        count = int(getattr(row, "count", 0) or 0)
        by_type[art_type] = by_type.get(art_type, 0) + count
        by_source[source] = by_source.get(source, 0) + count

    total_artifacts = sum(by_source.values())
    linked_artifacts = max(total_artifacts - orphan_count, 0)
    coverage_pct = (linked_artifacts / total_artifacts * 100.0) if total_artifacts else 0.0
    checked_at = datetime.utcnow().isoformat()
    last_sync = _project_last_sync(project)

    sources = [
        await _build_jira_source_health(
            db,
            project_id=project_id,
            integration=integrations.get("jira"),
            artifact_count=by_source.get("jira", 0),
            last_sync=last_sync,
            checked_at=checked_at,
        ),
        await _build_confluence_source_health(
            db,
            project_id=project_id,
            integration=integrations.get("confluence"),
            artifact_count=by_source.get("confluence", 0),
            last_sync=None,
            checked_at=checked_at,
        ),
        await _build_git_source_health(
            db,
            project_id=project_id,
            integrations=integrations,
            repositories=repositories,
            artifact_count=by_source.get("github", 0) + by_source.get("gitlab", 0),
            checked_at=checked_at,
        ),
    ]

    return {
        "project_id": project.id,
        "project_name": project.name or project.jira_key,
        "jira_key": project.jira_key,
        "last_sync": last_sync,
        "health_status": _compute_project_health_status(
            last_sync=last_sync,
            artifact_count=total_artifacts,
            source_statuses=[source["status"] for source in sources],
        ),
        "by_type": by_type,
        "by_source": by_source,
        "link_coverage": {
            "total_artifacts": total_artifacts,
            "linked_artifacts": linked_artifacts,
            "orphaned_artifacts": orphan_count,
            "coverage_pct": coverage_pct,
        },
        "repositories": [
            {
                "id": repo.id,
                "provider": getattr(repo.repository, "provider", None),
                "repo_slug": getattr(repo.repository, "repo_slug", None),
                "default_branch": getattr(repo.repository, "default_branch", None),
            }
            for repo in repositories
            if getattr(repo, "repository", None) is not None
        ],
        "sources": sources,
        "checked_at": checked_at,
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
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
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
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")

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
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Fix common consistency issues automatically.

    By default runs in dry_run mode to preview changes.
    Set dry_run=False to actually apply fixes.

    Returns:
    - fixed: Number of issues fixed
    - preview: List of fixes that would be applied (in dry_run mode)
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
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
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get detailed cycle detection analysis.

    Returns all cycles found with full artifact information.
    """
    if project_id is None and not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
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
