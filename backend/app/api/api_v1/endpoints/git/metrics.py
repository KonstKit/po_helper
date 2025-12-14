"""
Pull Request metrics and analytics module.
Provides comprehensive metrics for code review process optimization.
"""
from __future__ import annotations
import time
import copy
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import PullRequest, Artifact, ProjectRepository, Repository
from app.services.repository_resolver import repository_resolver

logger = logging.getLogger(__name__)

# Configuration
PR_HISTOGRAM_THRESHOLDS: List[float] = [4.0, 8.0, 12.0, 24.0, 48.0]
PR_HISTOGRAM_LABELS: List[str] = ["<=4h", "4-8h", "8-12h", "12-24h", "24-48h", ">48h"]
RECENT_THROUGHPUT_DAYS = 14
PR_METRICS_CACHE_TTL_SECONDS = 60
PR_METRICS_SAMPLE_LIMIT = 20

# Simple in-memory cache with TTL
_metrics_cache: Dict[
    Tuple[Optional[int], Optional[str], Optional[int], Optional[int]],
    Dict[str, Any]
] = {}


def histogram_counts(values: List[Optional[float]], thresholds: List[float]) -> List[int]:
    """Calculate histogram distribution of values against thresholds."""
    counts = [0] * (len(thresholds) + 1)

    for val in values:
        if val is None:
            continue

        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        placed = False
        for idx, threshold in enumerate(thresholds):
            if v <= threshold:
                counts[idx] += 1
                placed = True
                break

        if not placed:
            counts[-1] += 1

    return counts


def parse_iso_datetime(dt_val) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    try:
        if isinstance(dt_val, str):
            # Handle 'Z' timezone
            dt_obj = datetime.fromisoformat(dt_val.replace('Z', '+00:00'))
        elif isinstance(dt_val, datetime):
            dt_obj = dt_val
        else:
            return None

        # Ensure timezone awareness
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc)
        else:
            dt_obj = dt_obj.astimezone(timezone.utc)

        return dt_obj

    except Exception as e:
        logger.warning(f"Failed to parse datetime {dt_val}: {e}")
        return None


def datetime_to_iso(dt_val) -> Optional[str]:
    """Convert datetime to ISO string format."""
    dt_obj = parse_iso_datetime(dt_val)

    if dt_obj is None:
        return None

    if isinstance(dt_obj, str):
        return dt_obj

    try:
        return dt_obj.isoformat()
    except Exception:
        return str(dt_obj) if dt_obj else None


async def get_pull_requests_for_project(
    db: AsyncSession,
    project_id: Optional[int] = None,
    provider: Optional[str] = None
) -> List[PullRequest]:
    """Get pull requests filtered by project and provider."""
    # If project_id is provided, use project's repositories
    repository_ids = []
    if project_id is not None:
        # Get all repositories linked to the project
        repositories = await repository_resolver.get_all_repositories(project_id, db)

        # If provider is specified, filter repositories by provider
        if provider:
            provider_lower = provider.lower()
            repositories = [r for r in repositories if r.provider == provider_lower]

        repository_ids = [r.id for r in repositories]

        # If no repositories found for project, fall back to JIRA key matching
        if not repository_ids:
            # Get all PRs and filter by JIRA keys
            res = await db.execute(select(PullRequest))
            prs = list(res.scalars().all())

            # Filter by provider if specified
            if provider:
                provider_lower = provider.lower()
                prs = [pr for pr in prs if (pr.provider or '').lower() == provider_lower]

            # Filter by project through JIRA keys
            res_issues = await db.execute(
                select(Artifact.external_id).where(
                    Artifact.type == 'jira_issue',
                    Artifact.project_id == project_id
                )
            )
            issue_keys = {row[0] for row in res_issues.all()}

            if issue_keys:
                filtered = []
                for pr in prs:
                    jira_keys = pr.jira_keys or []
                    if any(k in issue_keys for k in jira_keys):
                        filtered.append(pr)
                prs = filtered

            return prs

    # Query PRs directly from linked repositories
    query = select(PullRequest)

    if repository_ids:
        query = query.where(PullRequest.repository_id.in_(repository_ids))
    elif provider:
        # If no project_id but provider is specified, filter by provider
        query = query.where(PullRequest.provider == provider.lower())

    res = await db.execute(query)
    prs = list(res.scalars().all())

    return prs


async def calculate_pr_metrics(
    db: AsyncSession,
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    limit: Optional[int] = None,
    since_days: Optional[int] = None,
    disable_cache: bool = False
) -> Dict[str, Any]:
    """Calculate comprehensive PR metrics with optional caching."""

    # Normalize parameters
    normalized_provider = (provider or "").lower() or None
    normalized_since = max(1, int(since_days)) if since_days is not None else None
    normalized_limit = int(limit) if limit is not None else None

    # Check cache
    cache_key = (project_id, normalized_provider, normalized_limit, normalized_since)
    ttl = max(0, PR_METRICS_CACHE_TTL_SECONDS)
    now_ts = time.time()

    if not disable_cache and ttl and cache_key in _metrics_cache:
        entry = _metrics_cache[cache_key]
        if now_ts - entry['ts'] <= ttl:
            cached = copy.deepcopy(entry['data'])
            cached['cache_hit'] = True
            return cached

    # Get PRs
    prs = await get_pull_requests_for_project(db, project_id, normalized_provider)

    # Sort by newest first
    def pr_time(p: PullRequest):
        return getattr(p, "opened_at", None) or getattr(p, "created_at", None)

    prs = sorted(prs, key=pr_time, reverse=True)

    # Filter by time range
    if normalized_since is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=normalized_since)
        recent: List[PullRequest] = []

        for pr in prs:
            # Use merged_at, closed_at, created_at, or opened_at
            ts = (
                getattr(pr, "merged_at", None) or
                getattr(pr, "closed_at", None) or
                getattr(pr, "created_at", None) or
                getattr(pr, "opened_at", None)
            )

            dt_obj = parse_iso_datetime(ts)
            if dt_obj and dt_obj >= cutoff:
                recent.append(pr)

        prs = recent

    # Apply limit
    if normalized_limit:
        max_limit = max(1, min(normalized_limit, 500))
        prs = prs[:max_limit]

    total = len(prs)

    # Extract metric values
    cycle_values = [
        float(pr.cycle_time_hours)
        for pr in prs
        if pr.cycle_time_hours is not None
    ]

    lead_values = [
        float(pr.lead_time_hours)
        for pr in prs
        if pr.lead_time_hours is not None
    ]

    review_values = [
        float(pr.time_to_first_review_hours)
        for pr in prs
        if pr.time_to_first_review_hours is not None
    ]

    # Calculate averages
    avg_cycle = round(sum(cycle_values) / len(cycle_values), 2) if cycle_values else 0.0
    avg_lead = round(sum(lead_values) / len(lead_values), 2) if lead_values else 0.0
    avg_first_review = round(sum(review_values) / len(review_values), 2) if review_values else 0.0

    # Calculate rework rate
    rework_prs = [pr for pr in prs if (getattr(pr, "rework_count", 0) or 0) > 0]
    rework_rate = round(len(rework_prs) / total, 3) if total else 0.0

    # Count by state
    states: Dict[str, int] = {}
    for pr in prs:
        st = (pr.state or "unknown").lower()
        states[st] = states.get(st, 0) + 1

    # Calculate histograms
    cycle_hist = histogram_counts(cycle_values, PR_HISTOGRAM_THRESHOLDS)
    lead_hist = histogram_counts(lead_values, PR_HISTOGRAM_THRESHOLDS)

    # Calculate recent throughput
    now_utc = datetime.now(timezone.utc)
    recent_cutoff = now_utc - timedelta(days=RECENT_THROUGHPUT_DAYS)
    merged_recent = 0

    for pr in prs:
        merged_dt = parse_iso_datetime(getattr(pr, "merged_at", None))
        if merged_dt and merged_dt >= recent_cutoff:
            merged_recent += 1

    # Get sample PRs for detailed view
    samples: List[Dict[str, Any]] = []
    for pr in prs[:PR_METRICS_SAMPLE_LIMIT]:
        samples.append({
            "id": pr.id,
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "cycle_time_hours": getattr(pr, "cycle_time_hours", None),
            "lead_time_hours": getattr(pr, "lead_time_hours", None),
            "time_to_first_review_hours": getattr(pr, "time_to_first_review_hours", None),
            "rework_count": getattr(pr, "rework_count", None),
            "opened_at": datetime_to_iso(getattr(pr, "opened_at", None)),
            "merged_at": datetime_to_iso(getattr(pr, "merged_at", None)),
            "closed_at": datetime_to_iso(getattr(pr, "closed_at", None)),
        })

    # Prepare result
    base_result = {
        "total": total,
        "avg_cycle_time_hours": avg_cycle,
        "avg_lead_time_hours": avg_lead,
        "avg_time_to_first_review_hours": avg_first_review,
        "cycle_samples": len(cycle_values),
        "lead_samples": len(lead_values),
        "first_review_samples": len(review_values),
        "rework_rate": rework_rate,
        "by_state": states,
        "histogram": {
            "bins": PR_HISTOGRAM_LABELS,
            "cycle_counts": cycle_hist,
            "lead_counts": lead_hist,
        },
        "recent_throughput": {
            "days": RECENT_THROUGHPUT_DAYS,
            "merged": merged_recent,
            "per_day": round(merged_recent / RECENT_THROUGHPUT_DAYS, 2) if RECENT_THROUGHPUT_DAYS else 0
        },
        "sample_prs": samples,
        "filters": {
            "project_id": project_id,
            "provider": normalized_provider,
            "since_days": normalized_since,
            "limit": normalized_limit
        }
    }

    # Cache the result
    result_to_return = copy.deepcopy(base_result)
    result_to_return["cache_hit"] = False

    if not disable_cache and ttl:
        cache_payload = copy.deepcopy(base_result)
        _metrics_cache[cache_key] = {"ts": now_ts, "data": cache_payload}

        # Clean old cache entries (simple TTL check)
        if len(_metrics_cache) > 100:  # Prevent unbounded growth
            keys_to_remove = []
            for k, v in _metrics_cache.items():
                if now_ts - v['ts'] > ttl * 2:
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                del _metrics_cache[k]

    return result_to_return


async def get_pr_list(
    db: AsyncSession,
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get list of pull requests with details."""

    # Get PRs
    prs = await get_pull_requests_for_project(db, project_id, provider)

    # Sort by newest first
    def pr_time(p):
        return getattr(p, 'opened_at', None) or getattr(p, 'created_at', None)

    prs = sorted(prs, key=pr_time, reverse=True)

    # Apply limit
    prs = prs[:max(1, min(limit, 200))]

    # Format output
    out = []
    for pr in prs:
        out.append({
            'id': pr.id,
            'provider': pr.provider,
            'repository_id': pr.repository_id,
            'number': pr.number,
            'title': pr.title,
            'state': pr.state,
            'author_login': pr.author_login,
            'jira_keys': pr.jira_keys,
            'opened_at': datetime_to_iso(pr.opened_at),
            'merged_at': datetime_to_iso(pr.merged_at),
            'closed_at': datetime_to_iso(pr.closed_at),
            'first_review_at': datetime_to_iso(getattr(pr, 'first_review_at', None)),
            'cycle_time_hours': getattr(pr, 'cycle_time_hours', None),
            'lead_time_hours': getattr(pr, 'lead_time_hours', None),
            'time_to_first_review_hours': getattr(pr, 'time_to_first_review_hours', None),
            'rework_count': getattr(pr, 'rework_count', None),
            'files_changed': getattr(pr, 'files_changed', None),
            'lines_added': getattr(pr, 'lines_added', None),
            'lines_deleted': getattr(pr, 'lines_deleted', None),
        })

    return {'total': len(out), 'pull_requests': out}


async def get_commits_for_issue(
    db: AsyncSession,
    jira_key: str
) -> Dict[str, Any]:
    """Get commits linked to a JIRA issue."""

    # Find issue artifact
    res_issue = await db.execute(
        select(Artifact).where(
            Artifact.type == "jira_issue",
            Artifact.external_id == jira_key
        )
    )
    issue = res_issue.scalar_one_or_none()

    if not issue:
        return {"total": 0, "commits": [], "error": "Issue not found"}

    # Find commit artifacts linked to the issue
    from app.models import ArtifactLink, Repository, Commit as CommitModel

    res_links = await db.execute(
        select(Artifact)
        .join(ArtifactLink, ArtifactLink.from_artifact_id == Artifact.id)
        .where(ArtifactLink.to_artifact_id == issue.id)
        .where(Artifact.type == "commit")
    )
    commit_artifacts = res_links.scalars().all()

    # Map to Commit rows and include repo info
    commits: List[Dict[str, Any]] = []

    for artifact in commit_artifacts:
        sha = artifact.external_id

        # Get commit details
        commit_model = None
        try:
            res_cm = await db.execute(
                select(CommitModel).where(CommitModel.sha == sha)
            )
            commit_model = res_cm.scalars().first()
        except Exception as e:
            logger.warning(f"Failed to get commit model for {sha}: {e}")

        # Get repository info
        repo_info = None
        if commit_model and commit_model.repository_id:
            try:
                res_repo = await db.execute(
                    select(Repository).where(Repository.id == commit_model.repository_id)
                )
                repo = res_repo.scalar_one_or_none()
                if repo:
                    repo_info = {
                        "provider": repo.provider,
                        "slug": repo.repo_slug,
                        "default_branch": repo.default_branch
                    }
            except Exception as e:
                logger.warning(f"Failed to get repository info: {e}")

        commits.append({
            "sha": sha,
            "short_sha": sha[:8],
            "message": (
                getattr(commit_model, 'message', None) or
                getattr(artifact, 'title', None) or
                ""
            ),
            "author_email": getattr(commit_model, 'author_email', None),
            "author_name": getattr(commit_model, 'author_name', None),
            "repo": repo_info,
            "artifact": {
                "id": artifact.id,
                "title": artifact.title,
                "url": artifact.url,
                "created_at": datetime_to_iso(artifact.created_at) if artifact.created_at else None
            },
        })

    return {
        "total": len(commits),
        "jira_key": jira_key,
        "commits": commits
    }