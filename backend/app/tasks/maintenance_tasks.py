from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.celery_async_runner import run_async
from app.core.celery_app import TASK_RETRY_KWARGS, celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.analytics import AnalyticsEvent
from app.models.traceability import Baseline, BaselineItem
from app.services.analytics.export_service import cleanup_old_exports
from app.services.sync_tracking import recover_stale_running_sync_tasks

logger = logging.getLogger(__name__)


@celery_app.task(name="maintenance.cleanup_exports", **TASK_RETRY_KWARGS)
def cleanup_exports_task() -> int:
    async def _cleanup() -> int:
        async with AsyncSessionLocal() as db:
            return await cleanup_old_exports(db, max_age_hours=settings.EXPORT_FILE_TTL_HOURS)

    deleted = run_async(_cleanup())
    logger.info("maintenance.cleanup_exports deleted=%s", deleted)
    return deleted


@celery_app.task(name="maintenance.cleanup_baselines", **TASK_RETRY_KWARGS)
def cleanup_baselines_task() -> int:
    retention_days = int(getattr(settings, "BASELINE_RETENTION_DAYS", 0))
    if retention_days <= 0:
        logger.info("maintenance.cleanup_baselines skipped retention_days=%s", retention_days)
        return 0

    async def _cleanup() -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Baseline.id).where(Baseline.created_at < cutoff))
            baseline_ids = [row[0] for row in result.all()]
            if not baseline_ids:
                return 0
            await db.execute(delete(BaselineItem).where(BaselineItem.baseline_id.in_(baseline_ids)))
            await db.execute(delete(Baseline).where(Baseline.id.in_(baseline_ids)))
            await db.commit()
            return len(baseline_ids)

    deleted = run_async(_cleanup())
    logger.info("maintenance.cleanup_baselines deleted=%s", deleted)
    return deleted


async def cleanup_analytics_events(retention_days: int) -> int:
    """Delete analytics events older than `retention_days`. Returns the
    deleted row count. Exposed for direct testing; the celery task wrapper
    below applies it on a schedule."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with AsyncSessionLocal() as db:
        result = await db.execute(delete(AnalyticsEvent).where(AnalyticsEvent.occurred_at < cutoff))
        await db.commit()
        return int(result.rowcount or 0)


@celery_app.task(name="maintenance.cleanup_analytics_events", **TASK_RETRY_KWARGS)
def cleanup_analytics_events_task() -> int:
    """Delete `analytics_event` rows older than ANALYTICS_RETENTION_DAYS.

    Without this, the metric aggregation queries are already bounded by
    the retention window, but the table itself grows indefinitely.
    """
    retention_days = int(getattr(settings, "ANALYTICS_RETENTION_DAYS", 0))
    if retention_days <= 0:
        logger.info(
            "maintenance.cleanup_analytics_events skipped retention_days=%s",
            retention_days,
        )
        return 0
    deleted = run_async(cleanup_analytics_events(retention_days))
    logger.info("maintenance.cleanup_analytics_events deleted=%s", deleted)
    return deleted


@celery_app.task(name="maintenance.recover_stale_sync_tasks", **TASK_RETRY_KWARGS)
def recover_stale_sync_tasks_task() -> int:
    async def _recover() -> int:
        async with AsyncSessionLocal() as db:
            recovered = await recover_stale_running_sync_tasks(db)
            if recovered:
                await db.commit()
            return recovered

    recovered = run_async(_recover())
    logger.info("maintenance.recover_stale_sync_tasks recovered=%s", recovered)
    return recovered
