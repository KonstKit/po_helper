from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import as_float

if TYPE_CHECKING:
    from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)


async def get_project_value_metrics(
    db: AsyncSession,
    project_id: int,
) -> Dict[str, Any]:
    start = perf_counter()
    logger.info("analytics.value_metrics.start project_id=%s", project_id)

    cache_service: Optional["CacheService"]
    cache_key: Optional[str]
    try:
        from app.services.cache_service import cache_service as _cache_service

        cache_service = _cache_service
        cache_key = cache_service._make_key("value_metrics", project_id)
    except ImportError:
        cache_service = None
        cache_key = None

    if cache_service and cache_key:
        cached_result = cache_service.get(cache_key)
        if cached_result:
            logger.info("analytics.value_metrics.cache_hit project_id=%s", project_id)
            return cached_result

    try:
        value_case = case((Task.value_delivered == True, Task.business_value), else_=0.0)  # noqa: E712
        stmt = select(
            func.coalesce(func.sum(Task.business_value), 0).label("total_value"),
            func.coalesce(func.sum(value_case), 0).label("value_delivered"),
            func.coalesce(func.sum(Task.spent_hours), 0).label("spent"),
        ).where(Task.project_id == project_id)

        result = await asyncio.wait_for(db.execute(stmt), timeout=10.0)
        row = result.mappings().first()

        total_value = as_float(row["total_value"] if row else 0)
        delivered = as_float(row["value_delivered"] if row else 0)
        spent = as_float(row["spent"] if row else 0)
        roi = delivered / spent if spent else 0.0

        response = {
            "value_delivered": round(delivered, 2),
            "total_spent_hours": round(spent, 2),
            "roi": round(roi, 2),
            "total_value": round(total_value, 2),
        }

        if cache_service and cache_key:
            cache_service.set(cache_key, response, ttl=120)

        logger.info(
            "analytics.value_metrics.success project_id=%s roi=%.2f duration=%.3f",
            project_id,
            response["roi"],
            perf_counter() - start,
        )
        return response
    except asyncio.TimeoutError:
        logger.error(
            "analytics.value_metrics.timeout project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        return {
            "value_delivered": 0.0,
            "total_spent_hours": 0.0,
            "roi": 0.0,
            "total_value": 0.0,
            "error": "timeout",
        }
    except Exception:
        logger.exception(
            "analytics.value_metrics.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        return {
            "value_delivered": 0.0,
            "total_spent_hours": 0.0,
            "roi": 0.0,
            "total_value": 0.0,
            "error": "db_error",
        }
