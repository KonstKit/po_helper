"""Project synchronization orchestrator coordinating all sync services."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.crypto import decrypt_str
from app.models import Project, Sprint, IntegrationSetting
from app.services.jira import JiraAuthError, JiraUnexpectedResponse
from app.services.jira_service import jira_service
from app.services.sync.issue_sync_service import IssueSyncService, IssueSyncResult
from app.services.sync.worklog_sync_service import WorklogSyncService, WorklogSyncResult
from app.services.sync.sprint_snapshot_service import SprintSnapshotService, SnapshotResult
from app.services.sync.board_sync_service import BoardSyncService, BoardSyncResult

logger = logging.getLogger(__name__)


@dataclass
class ProjectSyncResult:
    """Comprehensive result of project synchronization."""

    project_key: str
    project_id: int
    success: bool = False

    # Service results
    issues: Optional[IssueSyncResult] = None
    worklogs: Optional[WorklogSyncResult] = None
    snapshots: Optional[SnapshotResult] = None
    boards: Optional[BoardSyncResult] = None

    # Overall statistics
    total_issues: int = 0
    sync_duration_seconds: float = 0.0

    # Errors
    errors: List[tuple[str, str]] = field(default_factory=list)
    failure_reason: Optional[str] = None


class ProjectSyncOrchestrator:
    """
    Orchestrates all project synchronization operations.

    Coordinates:
    - Connection management
    - Issue synchronization (IssueSyncService)
    - Worklog import (WorklogSyncService)
    - Sprint snapshots (SprintSnapshotService)
    - Board/sprint mapping (BoardSyncService)
    - Project metadata updates
    - Error handling and notifications
    """

    def __init__(self):
        self.issue_sync = IssueSyncService()
        self.worklog_sync = WorklogSyncService(jira_service)
        self.snapshot_service = SprintSnapshotService()
        self.board_sync = BoardSyncService(jira_service)

    async def sync_project(
        self,
        project_key: str,
        project_id: int,
    ) -> ProjectSyncResult:
        """
        Orchestrate complete project synchronization.

        Each service can fail independently without affecting others.
        All errors are logged and collected in the result.

        Args:
            project_key: Jira project key
            project_id: Internal project ID

        Returns:
            ProjectSyncResult with comprehensive statistics and errors
        """
        start_time = datetime.utcnow()
        result = ProjectSyncResult(
            project_key=project_key,
            project_id=project_id,
        )

        try:
            logger.info(
                "sync_project_issues started for %s (project_id=%s)", project_key, project_id
            )

            # Ensure Jira connection
            await self._ensure_jira_connection()

            # Fetch issues from Jira
            issues = await self._fetch_issues(project_key)

            if not issues:
                result.failure_reason = "empty"
                await self._notify_failure(
                    project_key,
                    project_id,
                    "empty",
                    "No issues returned from Jira - project may be empty or check API permissions",
                )
                return result

            result.total_issues = len(issues)

            # Run each sync service independently
            result.issues = await self._sync_issues(project_key, project_id, issues)
            result.worklogs = await self._sync_worklogs(project_key, project_id, issues)
            result.snapshots = await self._sync_snapshots(project_id)
            result.boards = await self._sync_boards(project_key, project_id)

            # Update project metadata
            await self._update_project_metadata(project_id, issues)

            # Calculate project dates from sprints if not set
            await self._update_project_dates(project_key, project_id)

            result.success = True
            result.sync_duration_seconds = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                "Sync complete project=%s saved_issues=%d duration=%.2fs",
                project_key,
                result.total_issues,
                result.sync_duration_seconds,
            )

            await self._notify_success(project_key, project_id)

        except JiraAuthError as exc:
            logger.error("Jira auth error during sync for %s: %s", project_key, exc)
            result.failure_reason = "auth"
            result.errors.append(("auth", str(exc)))
            await self._notify_failure(project_key, project_id, "auth", str(exc))

        except JiraUnexpectedResponse as exc:
            logger.error("Unexpected Jira response during sync for %s: %s", project_key, exc)
            result.failure_reason = "unexpected"
            result.errors.append(("unexpected", str(exc)))
            await self._notify_failure(project_key, project_id, "unexpected", str(exc))

        except Exception as exc:
            logger.error("Error syncing issues for %s: %s", project_key, exc, exc_info=True)
            result.failure_reason = "error"
            result.errors.append(("sync", str(exc)))
            await self._notify_failure(project_key, project_id, "error", str(exc))

        return result

    async def _ensure_jira_connection(self) -> None:
        """Ensure Jira service is connected (for Celery workers)."""
        logger.info(
            "Jira service state: base_url=%s, has_auth=%s",
            jira_service.base_url,
            bool(jira_service.auth or jira_service.bearer_token),
        )

        if not getattr(jira_service, "base_url", None) or (
            jira_service.auth is None and jira_service.bearer_token is None
        ):
            try:
                async with AsyncSessionLocal() as db:
                    res = await db.execute(
                        select(IntegrationSetting).where(IntegrationSetting.kind == "jira")
                    )
                    row = res.scalar_one_or_none()

                    if row and row.base_url and row.api_token:
                        token = decrypt_str(row.api_token)
                        email = (
                            None
                            if getattr(settings, "JIRA_FORCE_PAT", True)
                            else (row.email or None)
                        )
                        jira_service.connect(row.base_url, email, token)
                        logger.info(
                            "Jira connected in worker using stored settings (base_url=%s, mode=%s)",
                            row.base_url,
                            "PAT" if email is None else "Basic",
                        )
            except Exception as e:
                logger.warning("Worker Jira bootstrap failed: %s", e)

    async def _fetch_issues(self, project_key: str) -> List[Dict[str, Any]]:
        """Fetch issues from Jira."""
        issues = await jira_service.async_get_project_issues(project_key)
        logger.info("Fetched %d issues for project %s", len(issues) if issues else 0, project_key)

        if not issues:
            logger.warning(
                "No issues fetched for project %s - this could mean the project is empty or there is a permission issue",
                project_key,
            )

        return issues

    async def _sync_issues(
        self,
        project_key: str,
        project_id: int,
        issues: List[Dict[str, Any]],
    ) -> Optional[IssueSyncResult]:
        """Sync issues with error isolation."""
        try:
            async with AsyncSessionLocal() as db:
                result = await self.issue_sync.sync_issues(
                    project_key,
                    project_id,
                    issues,
                    db,
                )
                return result
        except Exception as e:
            logger.error("Issue sync failed for %s: %s", project_key, e, exc_info=True)
            return None

    async def _sync_worklogs(
        self,
        project_key: str,
        project_id: int,
        issues: List[Dict[str, Any]],
    ) -> Optional[WorklogSyncResult]:
        """Sync worklogs with error isolation."""
        try:
            async with AsyncSessionLocal() as db:
                result = await self.worklog_sync.sync_worklogs(
                    project_key,
                    project_id,
                    issues,
                    db,
                )
                return result
        except Exception as e:
            logger.error("Worklog sync failed for %s: %s", project_key, e, exc_info=True)
            return None

    async def _sync_snapshots(self, project_id: int) -> Optional[SnapshotResult]:
        """Generate sprint snapshots with error isolation."""
        try:
            async with AsyncSessionLocal() as db:
                result = await self.snapshot_service.create_snapshots(
                    project_id,
                    db,
                )
                return result
        except Exception as e:
            logger.error("Sprint snapshots failed for project %d: %s", project_id, e, exc_info=True)
            return None

    async def _sync_boards(
        self,
        project_key: str,
        project_id: int,
    ) -> Optional[BoardSyncResult]:
        """Sync boards and sprints with error isolation."""
        try:
            async with AsyncSessionLocal() as db:
                result = await self.board_sync.sync_boards(
                    project_key,
                    project_id,
                    db,
                )
                return result
        except Exception as e:
            logger.error("Board sync failed for %s: %s", project_key, e, exc_info=True)
            return None

    async def _update_project_metadata(
        self,
        project_id: int,
        issues: List[Dict[str, Any]],
    ) -> None:
        """Update project metadata with sync information."""
        try:
            async with AsyncSessionLocal() as db:
                project_row = await db.execute(select(Project).where(Project.id == project_id))
                project = project_row.scalar_one_or_none()

                if project:
                    existing_meta = getattr(project, "meta", None) or {}
                    metadata = dict(existing_meta) if isinstance(existing_meta, dict) else {}
                    metadata["last_sync_at"] = datetime.utcnow().isoformat()
                    metadata["issues_count"] = len(issues)
                    project.meta = metadata
                    await db.commit()
        except Exception as e:
            logger.error("Failed to update project metadata: %s", e)

    async def _update_project_dates(self, project_key: str, project_id: int) -> None:
        """Calculate project dates from sprint data if not already set."""
        try:
            async with AsyncSessionLocal() as db:
                project_row = await db.execute(select(Project).where(Project.id == project_id))
                project = project_row.scalar_one_or_none()

                if not project or (project.start_date and project.end_date):
                    return

                sprint_rows = await db.execute(
                    select(Sprint)
                    .where(Sprint.project_id == project_id)
                    .where(Sprint.start_date.isnot(None))
                    .order_by(Sprint.start_date)
                )
                sprints = sprint_rows.scalars().all()

                if not sprints:
                    return

                # Set project start date to earliest sprint start
                if not project.start_date and sprints[0].start_date:
                    project.start_date = sprints[0].start_date
                    logger.info(
                        "Set project %s start_date from sprints: %s",
                        project_key,
                        project.start_date,
                    )

                # Set project end date to latest sprint end/complete date
                latest_end: Optional[datetime] = None
                for sprint in sprints:
                    sprint_end = sprint.complete_date or sprint.end_date
                    if sprint_end is None:
                        continue
                    if latest_end is None:
                        latest_end = sprint_end
                    elif sprint_end > latest_end:
                        latest_end = sprint_end

                if not project.end_date and latest_end:
                    project.end_date = latest_end
                    logger.info(
                        "Set project %s end_date from sprints: %s", project_key, project.end_date
                    )

                await db.commit()
        except Exception as e:
            logger.error("Failed to update project dates: %s", e)

    async def _notify_success(self, project_key: str, project_id: int) -> None:
        """Send success notification."""
        await self._notify("jira_sync_complete", project_key=project_key, project_id=project_id)

    async def _notify_failure(
        self,
        project_key: str,
        project_id: int,
        reason: str,
        detail: str,
    ) -> None:
        """Send failure notification."""
        await self._notify(
            "jira_sync_failed",
            project_key=project_key,
            project_id=project_id,
            reason=reason,
            detail=detail,
        )

    async def _notify(self, event_type: str, **payload: Any) -> None:
        """Send notification via WebSocket."""
        try:
            from app.core.notifications import connections

            await connections.broadcast_json({"type": event_type, **payload})
        except Exception:
            pass
