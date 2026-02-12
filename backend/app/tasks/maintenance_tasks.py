from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.traceability import Baseline, BaselineItem
from app.services.analytics.export_service import cleanup_old_exports

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="maintenance.cleanup_exports")
def cleanup_exports_task() -> int:
    async def _cleanup() -> int:
        async with AsyncSessionLocal() as db:
            return await cleanup_old_exports(db, max_age_hours=settings.EXPORT_FILE_TTL_HOURS)

    deleted = _run_async(_cleanup())
    logger.info("maintenance.cleanup_exports deleted=%s", deleted)
    return deleted


@celery_app.task(name="maintenance.cleanup_baselines")
def cleanup_baselines_task() -> int:
    retention_days = int(getattr(settings, "BASELINE_RETENTION_DAYS", 0))
    if retention_days <= 0:
        logger.info("maintenance.cleanup_baselines skipped retention_days=%s", retention_days)
        return 0

    async def _cleanup() -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Baseline.id).where(Baseline.created_at < cutoff)
            )
            baseline_ids = [row[0] for row in result.all()]
            if not baseline_ids:
                return 0
            await db.execute(
                delete(BaselineItem).where(BaselineItem.baseline_id.in_(baseline_ids))
            )
            await db.execute(delete(Baseline).where(Baseline.id.in_(baseline_ids)))
            await db.commit()
            return len(baseline_ids)

    deleted = _run_async(_cleanup())
    logger.info("maintenance.cleanup_baselines deleted=%s", deleted)
    return deleted
