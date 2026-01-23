from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TestResult

logger = logging.getLogger(__name__)


async def get_test_trend(
    db: AsyncSession,
    days: int = 14,
    project_id: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        since = datetime.utcnow() - timedelta(days=days)
        day_col = func.date(TestResult.created_at)
        fail_case = case((TestResult.status == "failed", 1), else_=0)
        stmt = (
            select(
                day_col.label("day"),
                func.count().label("total"),
                func.sum(fail_case).label("failed"),
            )
            .where(TestResult.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await db.execute(stmt)).mappings().all()
        trend: List[Dict[str, Any]] = [
            {
                "day": row["day"],
                "total": int(row["total"] or 0),
                "failed": int(row["failed"] or 0),
            }
            for row in rows
        ]
        return {"days": days, "project_id": project_id, "trend": trend}
    except SQLAlchemyError as exc:
        logger.warning("test_trend failed: %s", exc)
        return {"days": days, "project_id": project_id, "trend": [], "error": "db_error"}
