"""
Celery tasks for Jira synchronization.
Provides robust background processing with retry logic and progress tracking.
"""

from typing import Optional, Dict, Any, cast
from datetime import datetime, timezone
import logging
from celery import Task, states
from sqlalchemy import select
from app.core.celery_app import celery_app
from app.core.celery_async_runner import run_async
from app.core.database import AsyncSessionLocal
from app.services.jira_sync import perform_project_sync
from app.core.cache import redis_client as _redis_client
from app.models import IntegrationSetting, Project
from app.core.crypto import decrypt_str
from app.core.config import settings
from app.services.jira_service import jira_service
from app.services.sync_tracking import reserve_project_sync_task_lease, finish_sync_task
from app.utils import transactional_session
import json

logger = logging.getLogger(__name__)


async def _load_active_projects() -> list[Project]:
    async with AsyncSessionLocal() as db:
        setting = (
            await db.execute(
                select(IntegrationSetting).where(IntegrationSetting.kind == "jira")
            )
        ).scalar_one_or_none()
        if not setting or not setting.api_token:
            return []

        result = await db.execute(
            select(Project).where(Project.status == "active").order_by(Project.id)
        )
        return list(result.scalars().all())


async def _reserve_scheduled_sync_lease(project_id: int) -> tuple[int, bool]:
    async with AsyncSessionLocal() as db:
        async with transactional_session(db):
            task, created = await reserve_project_sync_task_lease(
                db,
                project_id=project_id,
                task_type="jira_sync",
                provider="jira",
                trigger="schedule",
            )
            return task.id, created


async def _fail_reserved_sync_task(task_id: int, message: str) -> None:
    async with AsyncSessionLocal() as db:
        await finish_sync_task(
            db,
            task_id,
            status="failed",
            error_code="dispatch_failed",
            error_message=message,
        )
        await db.commit()


class JiraSyncTask(Task):
    """Base task class with progress tracking for Jira sync."""

    def __init__(self):
        super().__init__()
        self.total_issues = 0
        self.processed_issues = 0
        self.created_count = 0
        self.updated_count = 0
        self.channel_id = None

    def update_progress(self, message: str, percent: Optional[int] = None):
        """Update task progress and send SSE update if channel is configured."""
        effective_percent = (
            percent
            if percent is not None
            else int((self.processed_issues / max(self.total_issues, 1)) * 100)
        )

        # Update Celery task state
        self.update_state(
            state="PROGRESS",
            meta={
                "current": self.processed_issues,
                "total": self.total_issues,
                "percent": effective_percent,
                "message": message,
                "created": self.created_count,
                "updated": self.updated_count,
            },
        )

        # Send SSE update if channel is configured
        if self.channel_id and redis_client:
            try:
                redis_client.publish(
                    f"jira_sync_{self.channel_id}",
                    json.dumps(
                        {
                            "type": "progress",
                            "percent": effective_percent,
                            "message": message,
                            "synced": self.processed_issues,
                            "created": self.created_count,
                            "updated": self.updated_count,
                            "task_id": self.request.id,
                        }
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to send SSE update: {e}")


@celery_app.task(
    bind=True,
    base=JiraSyncTask,
    name="jira.sync_project",
    max_retries=3,
    soft_time_limit=1800,  # 30 minutes soft limit
    time_limit=2400,  # 40 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
def sync_jira_project(
    self,
    project_key: str,
    project_id: int,
    channel_id: Optional[str] = None,
    trigger: str | None = "manual",
    sync_task_id: int | None = None,
) -> Dict[str, Any]:
    """
    Sync Jira project with robust error handling and progress tracking.

    Args:
        project_key: Jira project key
        project_id: Database project ID
        channel_id: Optional SSE channel for real-time updates

    Returns:
        Dictionary with sync statistics
    """
    self.channel_id = channel_id
    start_time = datetime.now(timezone.utc)

    try:
        logger.info(f"Starting Jira sync for project {project_key} (id={project_id})")
        self.update_progress(f"Initializing sync for {project_key}...", 0)

        # Ensure Jira service is connected (Celery doesn't run FastAPI startup)
        async def _ensure_jira_connected():
            if not getattr(jira_service, "base_url", None) or (
                jira_service.auth is None and jira_service.bearer_token is None
            ):
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
                            "Jira connected in Celery worker (base_url=%s, mode=%s)",
                            row.base_url,
                            "PAT" if email is None else "Basic",
                        )

        run_async(_ensure_jira_connected())

        # Run the actual sync
        self.update_progress(f"Syncing issues for {project_key}...", 10)
        run_async(
            perform_project_sync(
                project_key,
                project_id,
                trigger=trigger,
                sync_task_id=sync_task_id,
            )
        )

        # Calculate duration
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()

        self.update_progress(f"Sync completed for {project_key}", 100)

        result = {
            "status": "success",
            "project_key": project_key,
            "project_id": project_id,
            "duration": duration,
            "synced": self.processed_issues,
            "created": self.created_count,
            "updated": self.updated_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            f"Jira sync completed for {project_key}: "
            f"{self.processed_issues} issues, {duration:.1f}s"
        )

        return result

    except Exception as exc:
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        error_msg = str(exc)

        logger.error(f"Jira sync failed for {project_key}: {error_msg}", exc_info=True)

        # Send error notification
        if self.channel_id and redis_client:
            try:
                redis_client.publish(
                    f"jira_sync_{self.channel_id}",
                    json.dumps(
                        {
                            "type": "error",
                            "message": f"Sync failed: {error_msg}",
                            "task_id": self.request.id,
                        }
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to send error notification: {e}")

        # Update task state
        self.update_state(
            state=states.FAILURE,
            meta={"error": error_msg, "project_key": project_key, "duration": duration},
        )

        # Re-raise for Celery retry logic
        raise


@celery_app.task(name="jira.scheduled_sync")
def scheduled_jira_sync() -> Dict[str, Any]:
    """Scheduled task to sync all active Jira projects."""
    logger.info("Running scheduled Jira sync")

    projects = run_async(_load_active_projects())

    if not projects:
        logger.info("No active Jira projects or Jira not configured; skipping scheduled sync")
        return {"status": "skipped", "dispatched": 0}

    dispatched = 0
    skipped_running = 0
    dispatch_failed = 0
    for project in projects:
        if not project.jira_key:
            continue

        try:
            lease_task_id, created = run_async(_reserve_scheduled_sync_lease(project.id))
        except Exception as exc:
            dispatch_failed += 1
            logger.error(
                "Failed to reserve scheduled Jira sync lease for project=%s: %s",
                project.jira_key,
                exc,
            )
            continue

        if not created:
            skipped_running += 1
            logger.info(
                "Skipping scheduled Jira sync for project=%s: fresh running sync already exists",
                project.jira_key,
            )
            continue

        try:
            sync_jira_project.delay(project.jira_key, project.id, None, "schedule", lease_task_id)
            dispatched += 1
        except Exception as exc:
            dispatch_failed += 1
            logger.error(
                "Failed to dispatch scheduled Jira sync for project=%s: %s",
                project.jira_key,
                exc,
            )
            run_async(
                _fail_reserved_sync_task(
                    lease_task_id,
                    f"Scheduled Jira sync dispatch failed: {exc}",
                )
            )

    logger.info(
        "Scheduled Jira sync dispatched for %d project(s), skipped_running=%d, dispatch_failed=%d",
        dispatched,
        skipped_running,
        dispatch_failed,
    )
    return {
        "status": "ok",
        "dispatched": dispatched,
        "skipped_running": skipped_running,
        "dispatch_failed": dispatch_failed,
    }


redis_client: Any = cast(Any, _redis_client)
