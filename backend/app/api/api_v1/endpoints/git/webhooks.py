"""
Git webhooks handlers for GitHub and GitLab.
Handles push events, pull requests, and other repository events.
"""

from __future__ import annotations
import hmac
import hashlib
import json
import logging
from typing import Dict, Any, Optional

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.models import PullRequest
from app.utils import transactional_session
from app.core.rate_limiter import WebhookRateLimiter, CircuitBreaker
from app.core.metrics import metrics
from app.services.git.webhook_processor import (
    SECONDS_PER_HOUR,
    parse_iso_datetime,
    get_or_create_repository,
    process_commits,
    process_pull_request,
)

logger = logging.getLogger(__name__)

# Initialize rate limiter and circuit breaker
webhook_limiter = WebhookRateLimiter(
    max_per_minute=int(getattr(settings, "WEBHOOK_MAX_PER_MINUTE", 120))
)
webhook_breaker = CircuitBreaker(
    failure_threshold=int(getattr(settings, "CIRCUIT_FAILURE_THRESHOLD", 5)),
    base_backoff_seconds=float(getattr(settings, "CIRCUIT_BASE_BACKOFF_SECONDS", 5.0)),
    max_backoff_seconds=float(getattr(settings, "CIRCUIT_MAX_BACKOFF_SECONDS", 300.0)),
)


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

    result = await process_commits(db, provider, repo_slug, commits, branch)

    webhook_breaker.on_success(provider)
    return {"ok": True, "event": "push", **result}


async def handle_github_webhook(request: Request, db: AsyncSession) -> Dict[str, Any]:
    """Handle GitHub webhook events."""
    provider = "github"

    # Check circuit breaker
    if not webhook_breaker.allow(provider):
        metrics.inc("webhook_circuit_open", labels={"provider": provider})
        return {"ok": True, "status": "circuit_open"}

    # Check rate limit
    if not webhook_limiter.check_rate(provider):
        metrics.inc("webhook_rate_limited", labels={"provider": provider})
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
    metrics.inc("webhook_received", labels={"provider": provider, "event": event_type})

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

            result = await process_pull_request(db, provider, repo_slug, pr, action)

            webhook_breaker.on_success(provider)
            return {"ok": True, "event": f"pull_request:{action}", **result}

        elif event_type == "pull_request_review":
            # Handle first review timestamp
            pr = payload.get("pull_request") or {}
            number = pr.get("number")

            if number:
                repo_row = await get_or_create_repository(db, provider, repo_slug)
                res = await db.execute(
                    select(PullRequest).where(
                        PullRequest.repository_id == repo_row.id, PullRequest.number == number
                    )
                )
                pr_row = res.scalar_one_or_none()

                if pr_row and not pr_row.first_review_at:
                    review = payload.get("review") or {}
                    timestamp = review.get("submitted_at")

                    if timestamp:
                        pr_row.first_review_at = timestamp

                        # Calculate time to first review
                        if pr_row.opened_at:
                            opened_dt = parse_iso_datetime(pr_row.opened_at)
                            review_dt = parse_iso_datetime(timestamp)

                            if opened_dt and review_dt and review_dt >= opened_dt:
                                pr_row.time_to_first_review_hours = (
                                    review_dt - opened_dt
                                ).total_seconds() / SECONDS_PER_HOUR

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
        metrics.inc("webhook_errors", labels={"provider": provider, "type": type(e).__name__})
        webhook_breaker.on_failure(provider)
        raise


async def handle_gitlab_webhook(request: Request, db: AsyncSession) -> Dict[str, Any]:
    """Handle GitLab webhook events."""
    provider = "gitlab"

    # Check circuit breaker
    if not webhook_breaker.allow(provider):
        metrics.inc("webhook_circuit_open", labels={"provider": provider})
        return {"ok": True, "status": "circuit_open"}

    # Check rate limit
    if not webhook_limiter.check_rate(provider):
        metrics.inc("webhook_rate_limited", labels={"provider": provider})
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
    metrics.inc("webhook_received", labels={"provider": provider, "event": event_type})

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

            result = await process_pull_request(db, provider, repo_slug, pr_data, action)

            webhook_breaker.on_success(provider)
            return {"ok": True, "event": f"merge_request:{action}", **result}

        else:
            # Unknown event type
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_type, "status": "unhandled"}

    except Exception as e:
        logger.error(f"Error handling GitLab webhook: {e}")
        metrics.inc("webhook_errors", labels={"provider": provider, "type": type(e).__name__})
        webhook_breaker.on_failure(provider)
        raise


def verify_bitbucket_signature(
    secret: Optional[str], body: bytes, signature: Optional[str]
) -> bool:
    """Verify Bitbucket webhook signature (HMAC-SHA256).

    Bitbucket Cloud uses X-Hub-Signature header with SHA256.
    Bitbucket Server/Data Center may use X-Hub-Signature or a simple token.
    """
    if not secret:
        # No secret configured - accept in dev mode but log warning
        logger.warning("Bitbucket webhook secret not configured - accepting all requests")
        return True

    if not signature:
        logger.error("Bitbucket webhook signature missing")
        return False

    try:
        # Bitbucket uses "sha256=" prefix like GitHub
        mac = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256)
        expected = "sha256=" + mac.hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Error verifying Bitbucket signature: {e}")
        return False


async def handle_bitbucket_webhook(request: Request, db: AsyncSession) -> Dict[str, Any]:
    """Handle Bitbucket webhook events.

    Supports both Bitbucket Cloud and Bitbucket Server/Data Center.

    Cloud events (X-Event-Key header):
    - repo:push
    - pullrequest:created, pullrequest:updated, pullrequest:fulfilled, pullrequest:rejected

    Server events:
    - repo:refs_changed
    - pr:opened, pr:modified, pr:merged, pr:declined
    """
    provider = "bitbucket"

    # Check circuit breaker
    if not webhook_breaker.allow(provider):
        metrics.inc("webhook_circuit_open", labels={"provider": provider})
        return {"ok": True, "status": "circuit_open"}

    # Check rate limit
    if not webhook_limiter.check_rate(provider):
        metrics.inc("webhook_rate_limited", labels={"provider": provider})
        return {"ok": True, "status": "rate_limited"}

    # Verify signature (if configured)
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature")

    # Get webhook secret from settings
    bitbucket_secret = getattr(settings, "BITBUCKET_WEBHOOK_SECRET", None)
    if not verify_bitbucket_signature(bitbucket_secret, body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Bitbucket webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Get event type from header
    event_key = request.headers.get("X-Event-Key", "unknown")
    metrics.inc("webhook_received", labels={"provider": provider, "event": event_key})

    # Determine repository slug based on payload structure
    # Cloud format: repository.full_name = "workspace/repo"
    # Server format: repository.project.key + repository.slug
    repo = payload.get("repository") or {}
    repo_slug = repo.get("full_name") or repo.get("fullName")

    if not repo_slug:
        # Try Server format
        project = repo.get("project") or {}
        project_key = project.get("key")
        slug = repo.get("slug")
        if project_key and slug:
            repo_slug = f"{project_key}/{slug}"

    if not repo_slug:
        logger.error("Repository slug missing from Bitbucket webhook")
        raise HTTPException(status_code=400, detail="Repository information missing")

    try:
        # Handle Cloud events
        if event_key.startswith("repo:push") or event_key == "repo:refs_changed":
            # Push event
            # Cloud format: push.changes[].commits[]
            # Server format: changes[].commits[]
            push_data = payload.get("push") or payload
            changes = push_data.get("changes") or []
            commits = []

            for change in changes:
                change_commits = change.get("commits") or []
                for commit in change_commits:
                    # Normalize commit format
                    commits.append(
                        {
                            "id": commit.get("hash") or commit.get("id"),
                            "message": commit.get("message"),
                            "author": {
                                "name": (commit.get("author") or {})
                                .get("user", {})
                                .get("display_name")
                                or (commit.get("author") or {}).get("name"),
                                "email": (commit.get("author") or {}).get("emailAddress")
                                or (commit.get("author") or {})
                                .get("raw", "")
                                .split("<")[-1]
                                .rstrip(">"),
                            },
                            "url": (commit.get("links") or {}).get("html", {}).get("href")
                            or commit.get("url"),
                        }
                    )

            # Get branch name
            branch = None
            if changes:
                new_ref = changes[0].get("new") or {}
                branch = new_ref.get("name") or (new_ref.get("ref") or "").split("/")[-1]

            result = await process_commits(db, provider, repo_slug, commits, branch)
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_key, **result}

        elif event_key.startswith("pullrequest:") or event_key.startswith("pr:"):
            # Pull request event
            # Cloud: pullrequest object
            # Server: pullRequest object
            pr = payload.get("pullrequest") or payload.get("pullRequest") or {}

            # Normalize PR format
            pr_data = {
                "number": pr.get("id"),
                "title": pr.get("title"),
                "body": pr.get("description"),
                "state": _normalize_bitbucket_pr_state(pr.get("state")),
                "user": {
                    "username": (pr.get("author") or {}).get("display_name")
                    or (pr.get("author") or {}).get("username")
                    or (pr.get("author") or {}).get("name")
                },
                "html_url": (pr.get("links") or {}).get("html", {}).get("href")
                or pr.get("selfUrl"),
                "created_at": pr.get("created_on") or pr.get("createdDate"),
                "updated_at": pr.get("updated_on") or pr.get("updatedDate"),
            }

            # Handle merged state
            if event_key in ("pullrequest:fulfilled", "pr:merged"):
                pr_data["merged_at"] = pr.get("updated_on") or pr.get("updatedDate")

            # Handle closed/declined state
            if event_key in ("pullrequest:rejected", "pr:declined"):
                pr_data["closed_at"] = pr.get("updated_on") or pr.get("updatedDate")

            # Extract action from event key
            action = event_key.split(":")[-1] if ":" in event_key else None

            result = await process_pull_request(db, provider, repo_slug, pr_data, action)
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_key, **result}

        else:
            # Unknown event type - acknowledge but don't process
            webhook_breaker.on_success(provider)
            return {"ok": True, "event": event_key, "status": "unhandled"}

    except Exception as e:
        logger.error(f"Error handling Bitbucket webhook: {e}")
        metrics.inc("webhook_errors", labels={"provider": provider, "type": type(e).__name__})
        webhook_breaker.on_failure(provider)
        raise


def _normalize_bitbucket_pr_state(state: Optional[str]) -> str:
    """Normalize Bitbucket PR state to standard format."""
    if not state:
        return "unknown"

    state = state.upper()
    mapping = {
        "OPEN": "open",
        "MERGED": "merged",
        "DECLINED": "closed",
        "SUPERSEDED": "closed",
    }
    return mapping.get(state, state.lower())
