from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CoverageReport
from app.services.analytics_utils import as_float

logger = logging.getLogger(__name__)


async def get_coverage_trend(
    db: AsyncSession,
    days: int = 30,
    project_id: Optional[int] = None,
) -> Dict[str, Any]:
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        day_col = func.date(CoverageReport.created_at)
        stmt = (
            select(
                day_col.label("day"),
                func.avg(CoverageReport.line_coverage).label("avg_line"),
                func.avg(CoverageReport.branch_coverage).label("avg_branch"),
                func.count().label("count"),
            )
            .where(CoverageReport.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await db.execute(stmt)).mappings().all()
        trend: List[Dict[str, Any]] = [
            {
                "day": row["day"],
                "avg_line": round(as_float(row["avg_line"]), 4),
                "avg_branch": round(as_float(row["avg_branch"]), 4),
                "count": int(row["count"] or 0),
            }
            for row in rows
        ]
        return {"days": days, "project_id": project_id, "trend": trend}
    except SQLAlchemyError as exc:
        logger.warning("coverage_trend failed: %s", exc)
        return {"days": days, "project_id": project_id, "trend": [], "error": "db_error"}
