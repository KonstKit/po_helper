from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import as_float

if TYPE_CHECKING:
    from app.services.cache_service import CacheService

logger = logging.getLogger(__name__)


async def get_project_budget_hours(
    db: AsyncSession,
    project_id: int,
    top_n: int = 5,
) -> Dict[str, Any]:
    start = perf_counter()
    logger.info("analytics.budget_hours.start project_id=%s top_n=%s", project_id, top_n)

    cache_service: Optional["CacheService"]
    cache_key: Optional[str]
    try:
        from app.services.cache_service import cache_service as _cache_service

        cache_service = _cache_service
        cache_key = cache_service._make_key("budget_hours", project_id, top_n)
    except ImportError:
        cache_service = None
        cache_key = None

    if cache_service and cache_key:
        cached_result = cache_service.get(cache_key)
        if cached_result:
            logger.info("analytics.budget_hours.cache_hit project_id=%s", project_id)
            return cached_result

    try:
        totals_stmt = select(
            func.coalesce(func.sum(Task.estimate_hours), 0).label("estimate"),
            func.coalesce(func.sum(Task.spent_hours), 0).label("spent"),
        ).where(Task.project_id == project_id)

        diff = Task.spent_hours - Task.estimate_hours
        over_stmt = (
            select(Task.key, diff.label("delta"))
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_not(None))
            .where(Task.spent_hours.is_not(None))
            .where(diff > 0)
            .order_by(desc(diff))
            .limit(max(1, min(int(top_n or 5), 50)))
        )

        totals_result = await db.execute(totals_stmt)
        over_result = await db.execute(over_stmt)

        totals = totals_result.first()
        total_estimate = as_float(totals.estimate if totals else 0)
        total_spent = as_float(totals.spent if totals else 0)
        remaining = max(0.0, total_estimate - total_spent)
        overrun_hours = max(0.0, total_spent - total_estimate)

        top_overruns = [
            {"key": key, "overrun_hours": round(as_float(delta), 2)}
            for key, delta in over_result.all()
        ]

        response = {
            "total_estimate_hours": round(total_estimate, 2),
            "total_spent_hours": round(total_spent, 2),
            "remaining_hours": round(remaining, 2),
            "overrun": total_spent > total_estimate,
            "overrun_hours": round(overrun_hours, 2),
            "top_overruns": top_overruns,
        }

        if cache_service and cache_key:
            cache_service.set(cache_key, response, ttl=120)

        logger.info(
            "analytics.budget_hours.success project_id=%s overrun=%s duration=%.3f",
            project_id,
            response["overrun"],
            perf_counter() - start,
        )
        return response
    except Exception:
        logger.exception(
            "analytics.budget_hours.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        return {
            "total_estimate_hours": 0.0,
            "total_spent_hours": 0.0,
            "remaining_hours": 0.0,
            "overrun": False,
            "overrun_hours": 0.0,
            "top_overruns": [],
            "error": "query_error",
        }
