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
from app.models.traceability import SyncTask as SyncTaskModel
from app.services.jira import JiraAuthError, JiraUnexpectedResponse
from app.services.jira_service import jira_service
from app.services.integration_config import get_connector_overrides
from app.services.sync.issue_sync_service import IssueSyncService, IssueSyncResult
from app.services.sync.worklog_sync_service import WorklogSyncService, WorklogSyncResult
from app.services.sync.sprint_snapshot_service import SprintSnapshotService, SnapshotResult
from app.services.sync.board_sync_service import BoardSyncService, BoardSyncResult
from app.services.sync_tracking import (
    get_or_create_source,
    start_sync_task,
    finish_sync_task,
    touch_sync_task_heartbeat,
    upsert_sync_state,
)

logger = logging.getLogger(__name__)


LEASE_LOST_ERROR_CODE = "sync_lease_lost"
LEASE_ACQUIRE_ERROR_CODE = "sync_lease_acquire_failed"


class SyncLeaseError(RuntimeError):
    """Raised when Jira sync lease is missing, invalid, or cannot be acquired."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


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
        trigger: str | None = "manual",
        sync_task_id: int | None = None,
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
        sync_source_id: Optional[int] = None
        should_finalize_sync_task = False

        try:
            logger.info(
                "sync_project_issues started for %s (project_id=%s)", project_key, project_id
            )

            if sync_task_id is not None:
                async with AsyncSessionLocal() as tracking_db:
                    reserved_task = await tracking_db.get(SyncTaskModel, sync_task_id)
                    if reserved_task is None:
                        raise SyncLeaseError(
                            LEASE_LOST_ERROR_CODE,
                            (
                                f"Reserved Jira sync lease id={sync_task_id} "
                                "is missing; aborting worker execution"
                            ),
                        )
                    if (
                        reserved_task.status != "running"
                        or reserved_task.task_type != "jira_sync"
                        or reserved_task.project_id != project_id
                    ):
                        raise SyncLeaseError(
                            LEASE_LOST_ERROR_CODE,
                            (
                                f"Reserved Jira sync lease id={sync_task_id} is no longer valid "
                                f"(status={reserved_task.status}, task_type={reserved_task.task_type}, "
                                f"project_id={reserved_task.project_id}); aborting worker execution"
                            ),
                        )

                    sync_source_id = reserved_task.source_id
                    await touch_sync_task_heartbeat(tracking_db, sync_task_id)
                    await tracking_db.commit()
                    should_finalize_sync_task = True

            if sync_task_id is None:
                try:
                    async with AsyncSessionLocal() as tracking_db:
                        source = await get_or_create_source(
                            tracking_db, provider="jira", project_id=project_id
                        )
                        sync_source_id = source.id
                        task = await start_sync_task(
                            tracking_db,
                            task_type="jira_sync",
                            project_id=project_id,
                            source_id=sync_source_id,
                            trigger=trigger,
                        )
                        sync_task_id = task.id
                        await tracking_db.commit()
                        should_finalize_sync_task = True
                except Exception as exc:
                    raise SyncLeaseError(
                        LEASE_ACQUIRE_ERROR_CODE,
                        f"Failed to acquire Jira sync lease for project_id={project_id}: {exc}",
                    ) from exc

            # Ensure Jira connection
            await self._ensure_jira_connection(project_id)

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
            await self._heartbeat_sync_task(sync_task_id, {"issues_total": result.total_issues})

            # Run each sync service independently
            result.issues = await self._sync_issues(project_key, project_id, issues)
            await self._heartbeat_sync_task(
                sync_task_id,
                {
                    "issues_total": result.total_issues,
                    "issues_processed": result.issues.total_processed if result.issues else 0,
                    "issues_added": result.issues.total_added if result.issues else 0,
                    "issues_updated": result.issues.total_updated if result.issues else 0,
                },
            )
            result.worklogs = await self._sync_worklogs(project_key, project_id, issues)
            await self._heartbeat_sync_task(
                sync_task_id,
                {
                    "issues_total": result.total_issues,
                    "worklogs_imported": (
                        result.worklogs.total_worklogs_imported if result.worklogs else 0
                    ),
                },
            )
            result.snapshots = await self._sync_snapshots(project_id)
            await self._heartbeat_sync_task(
                sync_task_id,
                {
                    "issues_total": result.total_issues,
                    "snapshots_created": (
                        result.snapshots.total_snapshots_created if result.snapshots else 0
                    ),
                },
            )
            result.boards = await self._sync_boards(project_key, project_id, sync_task_id, result.total_issues)
            await self._heartbeat_sync_task(
                sync_task_id,
                {
                    "issues_total": result.total_issues,
                    "tasks_linked": result.boards.total_tasks_linked if result.boards else 0,
                },
            )

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

        except SyncLeaseError as exc:
            logger.warning("Jira sync lease check failed for %s: %s", project_key, exc)
            result.failure_reason = exc.error_code
            result.errors.append(("lease", str(exc)))
            await self._notify_failure(project_key, project_id, exc.error_code, str(exc))
            # Lease is not ours (or does not exist), so this worker must not mutate sync tracking.
            should_finalize_sync_task = False

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

        finally:
            if should_finalize_sync_task and sync_task_id is not None:
                item_counts: Dict[str, Any] = {"issues_total": result.total_issues}
                if result.issues is not None:
                    item_counts.update(
                        {
                            "issues_processed": result.issues.total_processed,
                            "issues_added": result.issues.total_added,
                            "issues_updated": result.issues.total_updated,
                        }
                    )
                if result.worklogs is not None:
                    item_counts.update(
                        {
                            "worklogs_imported": result.worklogs.total_worklogs_imported,
                            "worklog_issues_processed": result.worklogs.total_issues_processed,
                            "worklog_issues_skipped": result.worklogs.total_issues_skipped,
                        }
                    )
                if result.snapshots is not None:
                    item_counts.update(
                        {
                            "sprints_processed": result.snapshots.total_sprints_processed,
                            "snapshots_created": result.snapshots.total_snapshots_created,
                            "sprints_skipped": result.snapshots.sprints_skipped,
                        }
                    )
                if result.boards is not None:
                    item_counts.update(
                        {
                            "boards_processed": result.boards.total_boards_processed,
                            "sprints_synced": result.boards.total_sprints_synced,
                            "tasks_linked": result.boards.total_tasks_linked,
                        }
                    )
                if result.errors:
                    item_counts["error_count"] = len(result.errors)

                error_code = result.failure_reason or None
                error_message = result.errors[0][1] if result.errors else None
                status = "success" if result.success else "failed"

                try:
                    async with AsyncSessionLocal() as tracking_db:
                        await finish_sync_task(
                            tracking_db,
                            sync_task_id,
                            status=status,
                            item_counts=item_counts,
                            error_code=error_code,
                            error_message=error_message,
                        )
                        if sync_source_id is not None:
                            await upsert_sync_state(
                                tracking_db,
                                source_id=sync_source_id,
                                project_id=project_id,
                                last_event_id=str(sync_task_id),
                            )
                        await tracking_db.commit()
                except Exception as exc:
                    logger.warning("Failed to finalize Jira sync tracking: %s", exc)

        return result

    async def _heartbeat_sync_task(
        self,
        sync_task_id: Optional[int],
        item_counts: Optional[Dict[str, Any]] = None,
    ) -> None:
        if sync_task_id is None:
            return
        try:
            async with AsyncSessionLocal() as tracking_db:
                await touch_sync_task_heartbeat(
                    tracking_db,
                    sync_task_id,
                    item_counts=item_counts,
                )
                await tracking_db.commit()
        except Exception as exc:
            logger.debug("Failed to heartbeat Jira sync task id=%s: %s", sync_task_id, exc)

    async def _ensure_jira_connection(self, project_id: int | None = None) -> None:
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
                    overrides = await get_connector_overrides(db, project_id, "jira")
                    if overrides and not overrides.enabled:
                        raise JiraAuthError("Jira connector is disabled for this project")

                    res = await db.execute(
                        select(IntegrationSetting).where(IntegrationSetting.kind == "jira")
                    )
                    row = res.scalar_one_or_none()

                    if row and (
                        row.api_token or (overrides and overrides.settings.get("api_token"))
                    ):
                        token = decrypt_str(row.api_token)
                        if overrides and overrides.settings.get("api_token"):
                            token = str(overrides.settings.get("api_token"))
                        email = (
                            None
                            if getattr(settings, "JIRA_FORCE_PAT", True)
                            else (row.email or None)
                        )
                        base_url = row.base_url
                        if overrides and overrides.settings.get("base_url"):
                            base_url = str(overrides.settings.get("base_url"))
                        if overrides and overrides.settings.get("email"):
                            email = str(overrides.settings.get("email"))
                        if base_url and token:
                            jira_service.connect(base_url, email, token)
                        logger.info(
                            "Jira connected in worker using stored settings (base_url=%s, mode=%s)",
                            base_url,
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
                await db.commit()
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
        sync_task_id: Optional[int] = None,
        issues_total: int = 0,
    ) -> Optional[BoardSyncResult]:
        """Sync boards and sprints with error isolation."""
        try:
            async with AsyncSessionLocal() as db:
                async def _heartbeat_board_progress(item_counts: Dict[str, Any]) -> None:
                    payload = {"issues_total": issues_total}
                    payload.update(item_counts)
                    await self._heartbeat_sync_task(sync_task_id, payload)

                result = await self.board_sync.sync_boards(
                    project_key,
                    project_id,
                    db,
                    heartbeat_callback=_heartbeat_board_progress,
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
