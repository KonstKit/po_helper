"""Shared Git webhook processing logic reusable by endpoints and import service."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import metrics
from app.models import (
    Repository,
    Commit as CommitModel,
    Artifact,
    ArtifactLink,
    PullRequest,
)
from app.services.repository_resolver import repository_resolver
from app.services.sync_tracking import (
    get_or_create_source,
    start_sync_task,
    finish_sync_task,
    upsert_sync_state,
)
from app.utils import transactional_session, execute_with_lock

logger = logging.getLogger(__name__)

SECONDS_PER_HOUR = 3600.0


def parse_jira_keys_from_text(text: str) -> List[str]:
    """Extract JIRA issue keys from text."""
    if not text:
        return []
    return sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", text)))


def parse_iso_datetime(dt_val) -> Optional[datetime]:
    """Parse ISO datetime string to datetime object."""
    try:
        if isinstance(dt_val, str):
            return datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
        if isinstance(dt_val, datetime):
            return dt_val
        return None
    except Exception as e:
        logger.warning("Failed to parse datetime %s: %s", dt_val, e)
        try:
            metrics.inc("datetime_parse_failures", labels={"source": "webhook"})
        except Exception:
            pass
        return None


async def get_or_create_repository(
    db: AsyncSession, provider: str, slug: str, default_branch: Optional[str] = None
) -> Repository:
    """Get or create a repository record."""
    try:
        res = await db.execute(
            select(Repository).where(Repository.provider == provider, Repository.repo_slug == slug)
        )
        repo = res.scalar_one_or_none()

        if not repo:
            repo = Repository(provider=provider, repo_slug=slug, default_branch=default_branch)
            async with transactional_session(db):
                db.add(repo)
            await db.refresh(repo)
            logger.info("Created new repository: %s/%s", provider, slug)

        return repo
    except IntegrityError:
        await db.rollback()
        # Race condition - another request created it
        res = await db.execute(
            select(Repository).where(Repository.provider == provider, Repository.repo_slug == slug)
        )
        return res.scalar_one()
    except Exception as e:
        logger.error("Error creating repository %s/%s: %s", provider, slug, e)
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

        logger.info("Created link: %s -> %s", artifact.external_id, issue.external_id)
        return True

    except Exception as e:
        logger.error("Error linking artifacts: %s", e)
        return False


async def process_commits(
    db: AsyncSession,
    provider: str,
    repo_slug: str,
    commits: List[Dict[str, Any]],
    branch: Optional[str] = None,
    trigger: str | None = "webhook",
) -> Dict[str, Any]:
    """Process commits from webhook payload."""
    repo = await get_or_create_repository(db, provider, repo_slug, branch)
    project = await repository_resolver.get_project_by_repository(repo.id, db)
    project_id = project.id if project else None
    tenant_id = getattr(project, "tenant_id", None) if project else None

    sync_task_id: Optional[int] = None
    sync_source_id: Optional[int] = None
    last_commit_id: Optional[str] = None

    created = 0
    updated = 0
    links_created = 0
    errors = 0
    suggestions = []

    try:
        source = await get_or_create_source(
            db, provider=provider, project_id=project_id, tenant_id=tenant_id
        )
        sync_source_id = source.id
        task = await start_sync_task(
            db,
            task_type="git_commits",
            project_id=project_id,
            source_id=sync_source_id,
            trigger=trigger,
            cursor_in=branch,
        )
        sync_task_id = task.id
    except Exception as exc:
        logger.warning("Failed to start git commit sync tracking: %s", exc)

    for commit_data in commits:
        try:
            sha = commit_data.get("id") or commit_data.get("sha")
            if not sha:
                continue
            last_commit_id = sha

            message = commit_data.get("message") or commit_data.get("title", "")
            author = commit_data.get("author") or {}
            author_email = author.get("email") or (author.get("user") or {}).get("email")
            author_name = author.get("name") or author.get("username") or author.get("login")

            # Extract JIRA keys
            keys = parse_jira_keys_from_text(message)

            # Get or create commit record
            sel_cm = select(CommitModel).where(
                CommitModel.repository_id == repo.id, CommitModel.sha == sha
            )

            cm = (await execute_with_lock(db, sel_cm)).scalar_one_or_none()

            if not cm:
                cm = CommitModel(
                    repository_id=repo.id,
                    sha=sha,
                    message=message,
                    author_email=author_email,
                    author_name=author_name,
                    jira_keys=keys,
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
            artifact: Artifact | None = res.scalar_one_or_none()

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

            # Update artifact metadata
            await merge_artifact_meta(
                artifact,
                {
                    "repo": repo_slug,
                    "provider": provider,
                    "branch": branch,
                    "author_name": author_name,
                    "author_email": author_email,
                    "jira_keys": keys if keys else None,
                },
            )

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
                    suggestions.append(
                        {"jira_key": key, "commit": sha, "reason": "issue_not_found"}
                    )
                    continue

                if await link_artifact_to_issue(
                    db,
                    artifact,
                    issue,
                    link_type="relates_to",
                    confidence=0.9,
                    factors={"source": "smart_commit"},
                ):
                    links_created += 1

        except Exception as e:
            logger.error("Error processing commit %s: %s", commit_data.get("id"), e)
            errors += 1
            continue

    if sync_task_id is not None:
        try:
            item_counts = {
                "created": created,
                "updated": updated,
                "links_created": links_created,
                "suggestions": len(suggestions),
                "errors": errors,
                "commits": len(commits),
            }
            await finish_sync_task(
                db,
                sync_task_id,
                status="success",
                item_counts=item_counts,
                cursor_out=last_commit_id,
            )
            if sync_source_id is not None:
                await upsert_sync_state(
                    db,
                    source_id=sync_source_id,
                    project_id=project_id,
                    last_event_id=last_commit_id or repo_slug,
                    last_cursor=branch,
                )
        except Exception as exc:
            logger.warning("Failed to finalize git commit sync tracking: %s", exc)

    async with transactional_session(db):
        pass  # All db operations already executed above

    return {
        "created": created,
        "updated": updated,
        "links_created": links_created,
        "suggestions": suggestions,
    }


async def process_pull_request(
    db: AsyncSession,
    provider: str,
    repo_slug: str,
    pr_data: Dict[str, Any],
    action: Optional[str] = None,
    trigger: str | None = "webhook",
) -> Dict[str, Any]:
    """Process pull request from webhook payload."""
    sync_task_id: Optional[int] = None
    sync_source_id: Optional[int] = None
    project_id: Optional[int] = None
    number: Optional[int | str] = None

    try:
        number = pr_data.get("number") or pr_data.get("iid")
        if not number:
            return {"error": "PR number missing"}

        title = pr_data.get("title", "")
        body = pr_data.get("body") or pr_data.get("description", "")
        state = pr_data.get("state")
        author_login = (pr_data.get("user") or {}).get("login") or (pr_data.get("user") or {}).get(
            "username"
        )

        # Extract JIRA keys from title and body
        keys = parse_jira_keys_from_text(f"{title}\n{body}")

        # Get or create repository
        repo = await get_or_create_repository(db, provider, repo_slug)
        project = await repository_resolver.get_project_by_repository(repo.id, db)
        project_id = project.id if project else None
        tenant_id = getattr(project, "tenant_id", None) if project else None

        try:
            source = await get_or_create_source(
                db, provider=provider, project_id=project_id, tenant_id=tenant_id
            )
            sync_source_id = source.id
            task = await start_sync_task(
                db,
                task_type="git_pull_request",
                project_id=project_id,
                source_id=sync_source_id,
                trigger=trigger,
                cursor_in=str(number),
            )
            sync_task_id = task.id
        except Exception as exc:
            logger.warning("Failed to start git PR sync tracking: %s", exc)

        # Get or create PR record
        res = await db.execute(
            select(PullRequest).where(
                PullRequest.repository_id == repo.id, PullRequest.number == number
            )
        )
        pr_row = res.scalar_one_or_none()

        if not pr_row:
            pr_row = PullRequest(provider=provider, repository_id=repo.id, number=number)
            db.add(pr_row)

        # Update PR fields
        pr_row.title = title
        pr_row.state = state
        pr_row.author_login = author_login
        pr_row.head_sha = (pr_data.get("head") or {}).get("sha")
        pr_row.jira_keys = keys
        pr_row.files_changed = pr_data.get("changed_files")
        pr_row.lines_added = pr_data.get("additions")
        pr_row.lines_deleted = pr_data.get("deletions")

        # Update timestamps
        created_at = parse_iso_datetime(pr_data.get("created_at"))
        if created_at:
            pr_row.opened_at = created_at
        merged_at = parse_iso_datetime(pr_data.get("merged_at"))
        if merged_at:
            pr_row.merged_at = merged_at
        closed_at = parse_iso_datetime(pr_data.get("closed_at"))
        if closed_at:
            pr_row.closed_at = closed_at

        # Calculate metrics
        if pr_row.opened_at and pr_row.merged_at:
            opened_dt = parse_iso_datetime(pr_row.opened_at)
            merged_dt = parse_iso_datetime(pr_row.merged_at)

            if opened_dt and merged_dt and merged_dt >= opened_dt:
                delta_hours = (merged_dt - opened_dt).total_seconds() / SECONDS_PER_HOUR
                pr_row.cycle_time_hours = delta_hours
                pr_row.lead_time_hours = delta_hours

        # Track rework if PR is updated after review
        if action == "synchronize" and getattr(pr_row, "first_review_at", None):
            pr_row.rework_count = (getattr(pr_row, "rework_count", 0) or 0) + 1

        # Create or update artifact
        external_id = f"{repo_slug}#{number}"
        artifact_res = await db.execute(
            select(Artifact).where(
                Artifact.type == "pull_request",
                Artifact.source == provider,
                Artifact.external_id == external_id,
            )
        )
        artifact: Artifact | None = artifact_res.scalar_one_or_none()

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
        await merge_artifact_meta(
            artifact,
            {
                "repo": repo_slug,
                "provider": provider,
                "number": number,
                "author": author_login,
                "jira_keys": keys if keys else None,
            },
        )

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
                suggestions.append(
                    {"jira_key": key, "pull_request": external_id, "reason": "issue_not_found"}
                )
                continue

            if await link_artifact_to_issue(
                db,
                artifact,
                issue,
                link_type="relates_to",
                confidence=0.85,
                factors={"source": "pr_webhook"},
            ):
                links_created += 1

        if sync_task_id is not None:
            try:
                item_counts = {
                    "links_created": links_created,
                    "suggestions": len(suggestions),
                    "action": action,
                }
                await finish_sync_task(
                    db,
                    sync_task_id,
                    status="success",
                    item_counts=item_counts,
                    cursor_out=str(number),
                )
                if sync_source_id is not None:
                    await upsert_sync_state(
                        db,
                        source_id=sync_source_id,
                        project_id=project_id,
                        last_event_id=str(number),
                        last_cursor=str(number),
                    )
            except Exception as exc:
                logger.warning("Failed to finalize git PR sync tracking: %s", exc)

        async with transactional_session(db):
            pass  # All db operations already executed above

        return {
            "ok": True,
            "jira_keys": keys,
            "links_created": links_created,
            "suggestions": suggestions,
        }

    except Exception as e:
        logger.error("Error processing pull request: %s", e)
        await db.rollback()
        if sync_task_id is not None:
            try:
                await finish_sync_task(
                    db,
                    sync_task_id,
                    status="failed",
                    error_code="error",
                    error_message=str(e),
                )
                if sync_source_id is not None:
                    await upsert_sync_state(
                        db,
                        source_id=sync_source_id,
                        project_id=project_id,
                        last_event_id=str(number) if number is not None else None,
                    )
                await db.commit()
            except Exception as exc:
                logger.warning("Failed to finalize git PR sync failure: %s", exc)
        return {"error": str(e)}
