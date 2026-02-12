"""
Main Git API router combining webhooks, metrics, and CI/CD endpoints.
"""

from __future__ import annotations
from typing import Optional, Dict, Any

from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models import User
from app.core.crypto import decrypt_str
from app.models import IntegrationSetting, ProjectRepository, Repository
from app.services.github_client import fetch_pull_requests, GitHubAPIError

# Import submodules
from .git.webhooks import handle_github_webhook, handle_gitlab_webhook, handle_bitbucket_webhook
from .git.metrics import calculate_pr_metrics, get_pr_list, get_commits_for_issue
from .git.ci import process_ci_results

router = APIRouter()


# ============================================================================
# Webhook Endpoints
# ============================================================================


@router.post("/webhooks/github")
async def github_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Handle GitHub webhook events.

    Supports:
    - push events
    - pull_request events
    - pull_request_review events
    - workflow_run events

    Requires X-Hub-Signature-256 header for authentication.
    """
    return await handle_github_webhook(request, db)


@router.post("/webhooks/gitlab")
async def gitlab_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Handle GitLab webhook events.

    Supports:
    - push events
    - merge_request events

    Requires X-Gitlab-Token header for authentication.
    """
    return await handle_gitlab_webhook(request, db)


@router.post("/webhooks/bitbucket")
async def bitbucket_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Handle Bitbucket webhook events.

    Supports both Bitbucket Cloud and Bitbucket Server/Data Center:

    Cloud events (X-Event-Key header):
    - repo:push
    - pullrequest:created, pullrequest:updated, pullrequest:fulfilled, pullrequest:rejected

    Server events:
    - repo:refs_changed
    - pr:opened, pr:modified, pr:merged, pr:declined

    Requires HMAC-SHA256 signature verification when webhook secret is configured.
    """
    return await handle_bitbucket_webhook(request, db)


# ============================================================================
# Metrics Endpoints
# ============================================================================


@router.get("/pull-requests")
async def list_pull_requests(
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    List pull requests with filtering options.

    Args:
        project_id: Filter by project ID through JIRA issue links
        provider: Filter by provider (github/gitlab)
        limit: Maximum number of results (max: 200)

    Returns:
        List of pull requests with details including cycle time, lead time, etc.
    """
    if limit > 200:
        limit = 200

    return await get_pr_list(db, project_id, provider, limit)


@router.get("/pr-metrics")
async def pull_request_metrics(
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    limit: Optional[int] = None,
    since_days: Optional[int] = None,
    disable_cache: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Calculate comprehensive pull request metrics.

    Args:
        project_id: Filter by project ID
        provider: Filter by provider (github/gitlab)
        limit: Maximum number of PRs to analyze
        since_days: Only include PRs from last N days
        disable_cache: Force fresh calculation

    Returns:
        Metrics including:
        - Average cycle time, lead time, time to first review
        - Rework rate
        - State distribution
        - Time histograms
        - Recent throughput
        - Sample PRs for detailed analysis
    """
    return await calculate_pr_metrics(
        db=db,
        project_id=project_id,
        provider=provider,
        limit=limit,
        since_days=since_days,
        disable_cache=disable_cache,
    )


@router.get("/commits/{jira_key}")
async def commits_for_issue(
    jira_key: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Get commits linked to a JIRA issue.

    Args:
        jira_key: JIRA issue key (e.g., PROJ-123)

    Returns:
        List of commits with author information and repository details.
    """
    return await get_commits_for_issue(db, jira_key)


# ============================================================================
# CI/CD Endpoints
# ============================================================================


@router.post("/ci/results")
async def ci_results(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Ingest CI/CD test and coverage results.

    Accepts JSON payload with:
    - provider: CI provider name (e.g., 'jenkins', 'github-actions', 'gitlab-ci')
    - commit_sha: Git commit SHA
    - pr_number: Pull request number (optional)
    - baseline_id / baseline_ids: Optional baseline ID(s) to attach CI artifacts/links
    - projection_id / projection_ids: Optional projection ID(s) to attach CI artifacts/links
    - junit_xml: JUnit XML test results (string)
    - coverage: Coverage object with 'line' and 'branch' percentages
    - jacoco_xml: JaCoCo XML coverage report (string)
    - cobertura_xml: Cobertura XML coverage report (string)
    - report_url: URL to full report

    Returns:
        Summary of processed results including test counts and coverage saved.
    """
    return await process_ci_results(db, payload)


# ============================================================================
# Repository Management Endpoints
# ============================================================================


@router.get("/repositories")
async def list_repositories(
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    List configured repositories.

    Returns:
        List of repositories with provider and slug information.
    """
    from sqlalchemy import select
    from app.models import Repository

    result = await db.execute(select(Repository))
    repos = result.scalars().all()

    return {
        "total": len(repos),
        "repositories": [
            {
                "id": repo.id,
                "provider": repo.provider,
                "slug": repo.repo_slug,
                "default_branch": repo.default_branch,
                "created_at": repo.created_at.isoformat() if repo.created_at else None,
            }
            for repo in repos
        ],
    }


# ============================================================================
# Health Check
# ============================================================================


@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for Git integration.

    Returns:
        Status of the Git integration module.
    """
    return {
        "status": "healthy",
        "module": "git",
        "endpoints": {"webhooks": "active", "metrics": "active", "ci": "active"},
    }


@router.get("/github/projects/{project_id}/pulls")
async def github_project_pull_requests(
    project_id: int,
    state: str = "open",
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Fetch pull requests from GitHub for the project's linked repository."""
    result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == "github"))
    setting = result.scalar_one_or_none()
    if not setting or not setting.api_token:
        raise HTTPException(status_code=400, detail="GitHub integration is not configured")

    token = decrypt_str(setting.api_token)
    if not token:
        raise HTTPException(status_code=400, detail="GitHub token is not available")

    repo_result = await db.execute(
        select(Repository.repo_slug)
        .join(ProjectRepository, ProjectRepository.repository_id == Repository.id)
        .where(ProjectRepository.project_id == project_id, Repository.provider == "github")
        .order_by(ProjectRepository.is_primary.desc())
    )
    repo_row = repo_result.first()
    if not repo_row:
        raise HTTPException(status_code=404, detail="No GitHub repository linked to this project")

    repo_slug = repo_row[0]
    base_url = setting.base_url or None

    try:
        pulls = await fetch_pull_requests(
            token=token,
            repo_slug=repo_slug,
            base_url=base_url,
            state=state,
            per_page=limit,
        )
    except GitHubAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    simplified = []
    for pr in pulls:
        simplified.append(
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "draft": pr.get("draft"),
                "html_url": pr.get("html_url"),
                "user": {
                    "login": pr.get("user", {}).get("login"),
                    "avatar_url": pr.get("user", {}).get("avatar_url"),
                },
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "merged_at": pr.get("merged_at"),
                "additions": pr.get("additions"),
                "deletions": pr.get("deletions"),
                "changed_files": pr.get("changed_files"),
                "labels": [
                    label.get("name") for label in pr.get("labels", []) if isinstance(label, dict)
                ],
            }
        )

    return {
        "repository": repo_slug,
        "state": state,
        "count": len(simplified),
        "pulls": simplified,
    }
