"""Worklog synchronization service for Jira time tracking import."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import supports_for_update
from app.models import Task, WorkLog
from app.services.jira import JiraService
from app.utils import parse_datetime

logger = logging.getLogger(__name__)


@dataclass
class WorklogSyncResult:
    """Result of worklog synchronization operation."""

    total_issues_processed: int = 0
    total_worklogs_imported: int = 0
    total_issues_skipped: int = 0
    errors: List[tuple[str, str]] = field(default_factory=list)


class WorklogSyncService:
    """
    Service responsible for synchronizing Jira worklogs (time tracking data).

    Handles:
    - Fetching worklogs from Jira for each issue
    - Limiting to most recently updated issues (performance)
    - Upserting worklogs to database
    - Progress tracking and logging
    """

    MAX_ISSUES_FOR_WORKLOGS = 200  # Only process 200 most recent issues

    def __init__(self, jira_service: JiraService):
        self.jira_service = jira_service

    async def sync_worklogs(
        self,
        project_key: str,
        project_id: int,
        issues: List[Dict[str, Any]],
        db: AsyncSession,
    ) -> WorklogSyncResult:
        """
        Synchronize worklogs for project issues.

        Only processes the MAX_ISSUES_FOR_WORKLOGS most recently updated issues
        to avoid blocking on large projects.

        Args:
            project_key: Jira project key
            project_id: Internal project ID
            issues: List of issue data from Jira API
            db: Database session

        Returns:
            WorklogSyncResult with statistics and any errors
        """
        if not issues:
            logger.warning("No issues provided for worklog sync for project %s", project_key)
            return WorklogSyncResult()

        # Sort by updated date (most recent first) and limit
        sorted_issues = sorted(
            issues, key=lambda x: x.get("fields", {}).get("updated", ""), reverse=True
        )[: self.MAX_ISSUES_FOR_WORKLOGS]

        logger.info(
            "Starting worklogs import for project %s (processing %d of %d issues)",
            project_key,
            len(sorted_issues),
            len(issues),
        )

        result = WorklogSyncResult(total_issues_skipped=len(issues) - len(sorted_issues))

        # OPTIMIZATION: Pre-fetch all task IDs in single query to avoid N+1
        issue_keys: List[str] = [
            str(key) for key in (issue.get("key") for issue in sorted_issues) if key is not None
        ]
        task_id_map = await self._batch_fetch_task_ids(db, issue_keys, project_id)
        logger.debug("Pre-fetched %d task IDs for %d issue keys", len(task_id_map), len(issue_keys))

        for issue in sorted_issues:
            key = issue.get("key")
            if not key:
                continue

            result.total_issues_processed += 1

            # Progress logging every 50 issues
            if result.total_issues_processed % 50 == 0:
                logger.info(
                    "Worklogs import progress for %s: %d/%d issues processed, %d worklogs",
                    project_key,
                    result.total_issues_processed,
                    len(sorted_issues),
                    result.total_worklogs_imported,
                )

            try:
                issue_result = await self._sync_issue_worklogs(
                    key,
                    project_id,
                    db,
                    task_id_map=task_id_map,  # Pass pre-fetched map
                )
                result.total_worklogs_imported += issue_result
            except Exception as e:
                logger.error("Failed to sync worklogs for issue %s: %s", key, e, exc_info=True)
                result.errors.append((key, str(e)))

        logger.info(
            "Completed worklogs import for project %s (%d issues processed, %d worklogs, %d issues skipped)",
            project_key,
            result.total_issues_processed,
            result.total_worklogs_imported,
            result.total_issues_skipped,
        )

        return result

    async def _sync_issue_worklogs(
        self,
        issue_key: str,
        project_id: int,
        db: AsyncSession,
        task_id_map: Optional[Dict[str, int]] = None,
    ) -> int:
        """
        Sync worklogs for a single issue.

        Args:
            issue_key: Jira issue key
            project_id: Internal project ID
            db: Database session
            task_id_map: Optional pre-fetched map of issue_key -> task_id (N+1 optimization)

        Returns:
            Number of worklogs imported
        """
        # Fetch worklogs from Jira
        logs = await self.jira_service.async_get_issue_worklogs(issue_key)
        if not logs:
            return 0

        # Find the task in database - use pre-fetched map if available (N+1 optimization)
        task_id: Optional[int] = None
        if task_id_map is not None:
            task_id = task_id_map.get(issue_key)
        else:
            # Fallback to individual query (for backward compatibility)
            task_row = (
                await db.execute(
                    select(Task.id).where(Task.key == issue_key, Task.project_id == project_id)
                )
            ).scalar_one_or_none()
            task_id = task_row

        if not task_id:
            logger.warning("Task not found for issue %s in project %d", issue_key, project_id)
            return 0

        # Import worklogs
        try:
            async with db.begin():
                for worklog in logs:
                    await self._upsert_worklog(worklog, task_id, db)
            return len(logs)
        except IntegrityError:
            # Unique jira_id race with another worker – ignore duplicate and continue
            await db.rollback()
            logger.debug(
                "IntegrityError during worklog import for %s (likely duplicate)", issue_key
            )
            return 0

    async def _upsert_worklog(
        self,
        worklog: Dict[str, Any],
        task_id: int,
        db: AsyncSession,
    ) -> None:
        """Upsert a single worklog entry."""
        wl_id = worklog.get("id")
        if wl_id is None:
            return

        # Find existing worklog
        sel = select(WorkLog).where(WorkLog.jira_id == str(wl_id))
        if supports_for_update(db):
            sel = sel.with_for_update()

        db_wl = (await db.execute(sel)).scalar_one_or_none()

        if not db_wl:
            # Create new worklog
            db_wl = WorkLog(task_id=task_id, jira_id=str(wl_id))
            db.add(db_wl)

        # Update fields
        author = worklog.get("author") or {}
        db_wl.author_name = author.get("displayName")
        db_wl.author_email = author.get("emailAddress")
        db_wl.comment = worklog.get("comment")
        db_wl.time_spent_seconds = worklog.get("timeSpentSeconds")
        db_wl.started = parse_datetime(worklog.get("started"))
        db_wl.created = parse_datetime(worklog.get("created"))
        db_wl.updated = parse_datetime(worklog.get("updated"))

    async def _batch_fetch_task_ids(
        self,
        db: AsyncSession,
        issue_keys: List[str],
        project_id: int,
    ) -> Dict[str, int]:
        """
        Batch fetch task IDs for multiple issue keys in a single query.

        This is the N+1 optimization - instead of querying for each issue key
        individually during worklog sync, we pre-fetch all task IDs in one query.

        Args:
            db: Database session
            issue_keys: List of Jira issue keys (e.g., ['PROJ-1', 'PROJ-2', ...])
            project_id: Internal project ID

        Returns:
            Dict mapping issue_key -> task_id for O(1) lookup
        """
        if not issue_keys:
            return {}

        stmt = select(Task.key, Task.id).where(
            Task.key.in_(issue_keys), Task.project_id == project_id
        )
        result = await db.execute(stmt)
        rows = result.all()

        return {row[0]: row[1] for row in rows}
