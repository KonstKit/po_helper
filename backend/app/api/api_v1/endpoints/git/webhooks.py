"""
Git webhooks handlers for GitHub and GitLab.
Handles push events, pull requests, and other repository events.
"""
from __future__ import annotations
import hmac
import hashlib
import json
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import get_db
from app.models import (
    Repository,
    Commit as CommitModel,
    Artifact,
    ArtifactLink,
    PullRequest
)
from app.utils import transactional_session, execute_with_lock
from app.core.rate_limiter import WebhookRateLimiter, CircuitBreaker
from app.core.metrics import metrics
from app.services.repository_resolver import repository_resolver

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600.0

# Initialize rate limiter and circuit breaker
webhook_limiter = WebhookRateLimiter(
    max_per_minute=int(getattr(settings, 'WEBHOOK_MAX_PER_MINUTE', 120))
)
webhook_breaker = CircuitBreaker(
    failure_threshold=int(getattr(settings, 'CIRCUIT_FAILURE_THRESHOLD', 5)),
    base_backoff_seconds=float(getattr(settings, 'CIRCUIT_BASE_BACKOFF_SECONDS', 5.0)),
    max_backoff_seconds=float(getattr(settings, 'CIRCUIT_MAX_BACKOFF_SECONDS', 300.0)),
)


def parse_jira_keys_from_text(text: str) -> List[str]:
    """Extract JIRA issue keys from text."""
    import re
    if not text:
        return []
    # Match JIRA key pattern: PROJECT-123
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text)))


def parse_iso_datetime(dt_val) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    try:
        if isinstance(dt_val, str):
            # Handle 'Z' timezone
            return datetime.fromisoformat(dt_val.replace('Z', '+00:00'))
        elif isinstance(dt_val, datetime):
            return dt_val
        return None
    except Exception as e:
        logger.warning(f"Failed to parse datetime {dt_val}: {e}")
        try:
            metrics.inc('datetime_parse_failures', labels={'source': 'webhook'})
        except Exception:
            pass
        return None


def verify_github_signature(secret: Optional[str], body: bytes, signature: Optional[str]) -> bool:
    """Verify GitHub webhook signature."""
    if not secret:
        # No secret configured - accept in dev mode but log warning
        logger.warning("GitHub webhook secret not configured - accepting all requests")
        return True

    if not signature:
        logger.error("GitHub webhook signature missing")
        return False

    try:
        mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected = "sha256=" + mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Error verifying GitHub signature: {e}")
        return False


def verify_gitlab_token(token: Optional[str]) -> bool:
    """Verify GitLab webhook token."""
    if not settings.GITLAB_WEBHOOK_SECRET:
        logger.warning("GitLab webhook secret not configured - accepting all requests")
        return True

    if not token:
        logger.error("GitLab webhook token missing")
        return False

    return token == settings.GITLAB_WEBHOOK_SECRET


async def get_or_create_repository(
    db: AsyncSession,
    provider: str,
    slug: str,
    default_branch: Optional[str] = None
) -> Repository:
    """Get or create a repository record."""
    try:
        res = await db.execute(
            select(Repository).where(
                Repository.provider == provider,
                Repository.repo_slug == slug
            )
        )
        repo = res.scalar_one_or_none()

        if not repo:
            repo = Repository(
                provider=provider,
                repo_slug=slug,
                default_branch=default_branch
            )
            async with transactional_session(db):
                db.add(repo)
            await db.refresh(repo)
            logger.info(f"Created new repository: {provider}/{slug}")

        return repo
    except IntegrityError:
        await db.rollback()
        # Race condition - another request created it
        res = await db.execute(
            select(Repository).where(
                Repository.provider == provider,
                Repository.repo_slug == slug
            )
        )
        return res.scalar_one()
    except Exception as e:
        logger.error(f"Error creating repository {provider}/{slug}: {e}")
        raise


async def merge_artifact_meta(artifact: Artifact, extra: Dict[str, Any]) -> None:
    """Merge additional metadata into artifact."""
    meta = dict(artifact.meta or {})
    for key, value in extra.items():
        if value is not None:
            meta[key] = value
    artifact.meta = meta


async def link_artifact_to_issue(
    db: AsyncSession,
    artifact: Artifact,
    issue: Artifact,
    link_type: str = "relates_to",
    confidence: float = 0.9,
    factors: Optional[Dict[str, Any]] = None,
) -> bool:
    """Create a link between an artifact and a JIRA issue."""
    try:
        # Inherit project and tenant from issue
        if issue.project_id and not artifact.project_id:
            artifact.project_id = issue.project_id
        if issue.tenant_id and not artifact.tenant_id:
            artifact.tenant_id = issue.tenant_id

        # Check if link already exists
        res = await db.execute(
            select(ArtifactLink).where(
                ArtifactLink.from_artifact_id == artifact.id,
                ArtifactLink.to_artifact_id == issue.id,
                ArtifactLink.link_type == link_type,
            )
        )

        if res.scalar_one_or_none():
            return False

        # Create new link
        link = ArtifactLink(
            from_artifact_id=artifact.id,
            to_artifact_id=issue.id,
            link_type=link_type,
            confidence=confidence,
            confidence_factors=factors or {},
            project_id=issue.project_id,
            tenant_id=issue.tenant_id,
        )
        db.add(link)
        await db.flush()

        logger.info(f"Created link: {artifact.external_id} -> {issue.external_id}")
        return True

    except Exception as e:
        logger.error(f"Error linking artifacts: {e}")
        return False


async def process_commits(
    db: AsyncSession,
    provider: str,
    repo_slug: str,
    commits: List[Dict[str, Any]],
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Process commits from webhook payload."""
    repo = await get_or_create_repository(db, provider, repo_slug, branch)
    project = await repository_resolver.get_project_by_repository(repo.id, db)
    project_id = project.id if project else None
    tenant_id = getattr(project, 'tenant_id', None) if project else None

    created = 0
    updated = 0
    links_created = 0
    suggestions = []

    for commit_data in commits:
        try:
            sha = commit_data.get("id") or commit_data.get("sha")
            if not sha:
                continue

            message = commit_data.get("message") or commit_data.get("title", "")
            author = commit_data.get("author") or {}
            author_email = author.get("email") or (author.get("user") or {}).get("email")
            author_name = author.get("name") or author.get("username") or author.get("login")

            # Extract JIRA keys
            keys = parse_jira_keys_from_text(message)

            # Get or create commit record
            sel_cm = select(CommitModel).where(
                CommitModel.repository_id == repo.id,
                CommitModel.sha == sha
            )

            cm = (await execute_with_lock(db, sel_cm)).scalar_one_or_none()

            if not cm:
                cm = CommitModel(
                    repository_id=repo.id,
                    sha=sha,
                    message=message,
                    author_email=author_email,
                    author_name=author_name,
                    jira_keys=keys
                )
                db.add(cm)
                created += 1
            else:
                cm.message = message
                cm.author_email = author_email
                cm.author_name = author_name
                cm.jira_keys = keys
                updated += 1

            # Create or update artifact
            res = await db.execute(
                select(Artifact).where(
                    Artifact.type == "commit",
                    Artifact.source == provider,
                    Artifact.external_id == sha,
                )
            )
            artifact = res.scalar_one_or_none()

            if not artifact:
                artifact = Artifact(
                    type="commit",
                    source=provider,
                    external_id=sha,
                    display_key=sha[:8],
                    title=message.splitlines()[0][:200] if message else None,
                    url=commit_data.get("url") or commit_data.get("html_url"),
                )
                db.add(artifact)
                await db.flush()
            if project_id and artifact.project_id != project_id:
                artifact.project_id = project_id
            if tenant_id is not None and artifact.tenant_id != tenant_id:
                artifact.tenant_id = tenant_id

        # Update artifact metadata        # Update artifact metadata
            await merge_artifact_meta(artifact, {
                "repo": repo_slug,
                "provider": provider,
                "branch": branch,
                "author_name": author_name,
                "author_email": author_email,
                "jira_keys": keys if keys else None
            })

            # Link to JIRA issues
            for key in keys:
                res_issue = await db.execute(
                    select(Artifact).where(
                        Artifact.type == "jira_issue",
                        Artifact.external_id == key,
                    )
                )
                issue = res_issue.scalar_one_or_none()

                if not issue:
                    suggestions.append({
                        "jira_key": key,
                        "commit": sha,
                        "reason": "issue_not_found"
                    })
                    continue

                if await link_artifact_to_issue(
                    db, artifact, issue,
                    link_type="relates_to",
                    confidence=0.9,
                    factors={"source": "smart_commit"}
                ):
                    links_created += 1

        except Exception as e:
            logger.error(f"Error processing commit {commit_data.get('id')}: {e}")
            continue

    async with transactional_session(db):
        pass  # All db operations already executed above

    return {
        "created": created,
        "updated": updated,
        "links_created": links_created,
        "suggestions": suggestions
    }


async def process_pull_request(
    db: AsyncSession,
    provider: str,
    repo_slug: str,
    pr_data: Dict[str, Any],
    action: Optional[str] = None
) -> Dict[str, Any]:
    """Process pull request from webhook payload."""
    try:
        number = pr_data.get("number") or pr_data.get("iid")
        if not number:
            return {"error": "PR number missing"}

        title = pr_data.get("title", "")
        body = pr_data.get("body") or pr_data.get("description", "")
        state = pr_data.get("state")
        author_login = (pr_data.get("user") or {}).get("login") or (pr_data.get("user") or {}).get("username")

        # Extract JIRA keys from title and body
        keys = parse_jira_keys_from_text(f"{title}\n{body}")

        # Get or create repository
        repo = await get_or_create_repository(db, provider, repo_slug)
        project = await repository_resolver.get_project_by_repository(repo.id, db)
        project_id = project.id if project else None
        tenant_id = getattr(project, 'tenant_id', None) if project else None

        # Get or create PR record
        res = await db.execute(
            select(PullRequest).where(
                PullRequest.repository_id == repo.id,
                PullRequest.number == number
            )
        )
        pr_row = res.scalar_one_or_none()

        if not pr_row:
            pr_row = PullRequest(
                provider=provider,
                repository_id=repo.id,
                number=number
            )
            db.add(pr_row)

        # Update PR fields
        pr_row.title = title
        pr_row.state = state
        pr_row.author_login = author_login
        pr_row.head_sha = (pr_data.get('head') or {}).get('sha')
        pr_row.jira_keys = keys
        pr_row.files_changed = pr_data.get('changed_files')
        pr_row.lines_added = pr_data.get('additions')
        pr_row.lines_deleted = pr_data.get('deletions')

        # Update timestamps
        if pr_data.get('created_at'):
            pr_row.opened_at = pr_data.get('created_at')
        if pr_data.get('merged_at'):
            pr_row.merged_at = pr_data.get('merged_at')
        if pr_data.get('closed_at'):
            pr_row.closed_at = pr_data.get('closed_at')

        # Calculate metrics
        if pr_row.opened_at and pr_row.merged_at:
            opened_dt = parse_iso_datetime(pr_row.opened_at)
            merged_dt = parse_iso_datetime(pr_row.merged_at)

            if opened_dt and merged_dt and merged_dt >= opened_dt:
                delta_hours = (merged_dt - opened_dt).total_seconds() / SECONDS_PER_HOUR
                pr_row.cycle_time_hours = delta_hours
                pr_row.lead_time_hours = delta_hours

        # Track rework if PR is updated after review
        if action == 'synchronize' and getattr(pr_row, 'first_review_at', None):
            pr_row.rework_count = (getattr(pr_row, 'rework_count', 0) or 0) + 1

        # Create or update artifact
        external_id = f"{repo_slug}#{number}"
        res = await db.execute(
            select(Artifact).where(
                Artifact.type == "pull_request",
                Artifact.source == provider,
                Artifact.external_id == external_id,
            )
        )
        artifact = res.scalar_one_or_none()

        if not artifact:
            artifact = Artifact(
                type="pull_request",
                source=provider,
                external_id=external_id,
                display_key=f"#{number}",
                title=title,
                status=state,
                url=pr_data.get("html_url") or pr_data.get("url"),
            )
            db.add(artifact)
            await db.flush()
        else:
            artifact.title = title
            artifact.status = state
            if pr_data.get("html_url") or pr_data.get("url"):
                artifact.url = pr_data.get("html_url") or pr_data.get("url")
        if project_id and artifact.project_id != project_id:
            artifact.project_id = project_id
        if tenant_id is not None and artifact.tenant_id != tenant_id:
            artifact.tenant_id = tenant_id

        # Update artifact metadata
        await merge_artifact_meta(artifact, {
            "repo": repo_slug,
            "provider": provider,
            "number": number,
            "author": author_login,
            "jira_keys": keys if keys else None
        })

        # Link to JIRA issues
        links_created = 0
        suggestions = []

        for key in keys:
            res_issue = await db.execute(
                select(Artifact).where(
                    Artifact.type == "jira_issue",
                    Artifact.external_id == key,
                )
            )
            issue = res_issue.scalar_one_or_none()

            if not issue:
                suggestions.append({
                    "jira_key": key,
                    "pull_request": external_id,
                    "reason": "issue_not_found"
                })
                continue

            if await link_artifact_to_issue(
                db, artifact, issue,
                link_type="relates_to",
                confidence=0.85,
                factors={"source": "pr_webhook"}
            ):
                links_created += 1

        async with transactional_session(db):
            pass  # All db operations already executed above

        return {
            "ok": True,
            "jira_keys": keys,
            "links_created": links_created,
            "suggestions": suggestions
        }

    except Exception as e:
        logger.error(f"Error processing pull request: {e}")
        await db.rollback()
        return {"error": str(e)}


async def _handle_push_event(
    db: AsyncSession,
    provider: str,
    repo_slug: str,
    payload: Dict[str, Any],
    webhook_breaker: CircuitBreaker,
) -> Dict[str, Any]:
    """
    Handle push events for both GitHub and GitLab webhooks.

    This utility eliminates the repetitive 16-line pattern of:
    - Extracting branch name from ref
    - Getting commits from payload
    - Calling process_commits
    - Marking circuit breaker as successful
    - Returning result

    Usage:
        result = await _handle_push_event(db, provider, repo_slug, payload, webhook_breaker)
        return result

    Args:
        db: Database session
        provider: Git provider ('github' or 'gitlab')
        repo_slug: Repository slug (e.g., 'owner/repo')
        payload: Webhook payload containing ref and commits
        webhook_breaker: Circuit breaker instance

    Returns:
        Dict with ok, event, and result from process_commits
    """
    branch = (payload.get("ref") or "").split("/")[-1]
    commits = payload.get("commits") or []

    result = await process_commits(
        db, provider, repo_slug, commits, branch
    )

    webhook_breaker.on_success(provider)
    return {"ok": True, "event": "push", **result}


async def handle_github_webhook(
    request: Request,
    db: AsyncSession
) -> Dict[str, Any]:
    """Handle GitHub webhook events."""
    provider = 'github'

    # Check circuit breaker
    if not webhook_breaker.allow(provider):
        metrics.inc('webhook_circuit_open', labels={'provider': provider})
        return {"ok": True, "status": "circuit_open"}

    # Check rate limit
    if not webhook_limiter.check_rate(provider):
        metrics.inc('webhook_rate_limited', labels={'provider': provider})
        return {"ok": True, "status": "rate_limited"}

    # Verify signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")

    if not verify_github_signature(settings.GITHUB_WEBHOOK_SECRET, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse GitHub webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get event type
    event_type = request.headers.get("X-GitHub-Event", "unknown")
    metrics.inc('webhook_received', labels={'provider': provider, 'event': event_type})

    # Get repository info
    repo = payload.get("repository") or {}
    repo_slug = repo.get("full_name", "")

    if not repo_slug:
        logger.error("Repository slug missing from GitHub webhook")
        raise HTTPException(status_code=400, detail="Repository information missing")

    try:
        # Handle different event types
        if event_type == "push":
            return await _handle_push_event(db, provider, repo_slug, payload, webhook_breaker)

        elif event_type == "pull_request":
            action = payload.get("action")
            pr = payload.get("pull_request") or {}

            result = await process_pull_request(
                db, provider, repo_slug, pr, action
            )

            webhook_breaker.on_success(provider)
            return {"ok": True, "event": f"pull_request:{action}", **result}

        elif event_type == "pull_request_review":
            # Handle first review timestamp
            pr = payload.get('pull_request') or {}
            number = pr.get('number')

            if number:
                repo_row = await get_or_create_repository(db, provider, repo_slug)
                res = await db.execute(
                    select(PullRequest).where(
                        PullRequest.repository_id == repo_row.id,
                        PullRequest.number == number
                    )
                )
                pr_row = res.scalar_one_or_none()

                if pr_row and not pr_row.first_review_at:
                    review = payload.get('review') or {}
                    timestamp = review.get('submitted_at')

                    if timestamp:
                        pr_row.first_review_at = timestamp

                        # Calculate time to first review
                        if pr_row.opened_at:
                            opened_dt = parse_iso_datetime(pr_row.opened_at)
                            review_dt = parse_iso_datetime(timestamp)

                            if opened_dt and review_dt and review_dt >= opened_dt:
                                pr_row.time_to_first_review_hours = (
                                    (review_dt - opened_dt).total_seconds() / SECONDS_PER_HOUR
                                )

                        async with transactional_session(db):
                            pass  # All db operations already executed above

            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_type}

        else:
            # Unknown event type - acknowledge but don't process
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_type, "status": "unhandled"}

    except Exception as e:
        logger.error(f"Error handling GitHub webhook: {e}")
        metrics.inc('webhook_errors', labels={'provider': provider, 'type': type(e).__name__})
        webhook_breaker.on_failure(provider)
        raise


async def handle_gitlab_webhook(
    request: Request,
    db: AsyncSession
) -> Dict[str, Any]:
    """Handle GitLab webhook events."""
    provider = 'gitlab'

    # Check circuit breaker
    if not webhook_breaker.allow(provider):
        metrics.inc('webhook_circuit_open', labels={'provider': provider})
        return {"ok": True, "status": "circuit_open"}

    # Check rate limit
    if not webhook_limiter.check_rate(provider):
        metrics.inc('webhook_rate_limited', labels={'provider': provider})
        return {"ok": True, "status": "rate_limited"}

    # Verify token
    token = request.headers.get("X-Gitlab-Token")
    if not verify_gitlab_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    # Parse payload
    try:
        payload = await request.json()
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse GitLab webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get event type
    event_type = payload.get("object_kind", "unknown")
    metrics.inc('webhook_received', labels={'provider': provider, 'event': event_type})

    # Get repository info
    project = payload.get("project") or {}
    repo_slug = project.get("path_with_namespace", "")

    if not repo_slug:
        logger.error("Repository slug missing from GitLab webhook")
        raise HTTPException(status_code=400, detail="Repository information missing")

    try:
        # Handle different event types
        if event_type == "push":
            return await _handle_push_event(db, provider, repo_slug, payload, webhook_breaker)

        elif event_type == "merge_request":
            attributes = payload.get("object_attributes") or {}
            action = attributes.get("action")

            # Map GitLab MR to GitHub PR format
            pr_data = {
                "number": attributes.get("iid"),
                "title": attributes.get("title"),
                "body": attributes.get("description"),
                "state": attributes.get("state"),
                "user": {"username": payload.get("user", {}).get("username")},
                "created_at": attributes.get("created_at"),
                "merged_at": attributes.get("merged_at"),
                "closed_at": attributes.get("closed_at"),
            }

            result = await process_pull_request(
                db, provider, repo_slug, pr_data, action
            )

            webhook_breaker.on_success(provider)
            return {"ok": True, "event": f"merge_request:{action}", **result}

        else:
            # Unknown event type
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_type, "status": "unhandled"}

    except Exception as e:
        logger.error(f"Error handling GitLab webhook: {e}")
        metrics.inc('webhook_errors', labels={'provider': provider, 'type': type(e).__name__})
        webhook_breaker.on_failure(provider)
        raise


