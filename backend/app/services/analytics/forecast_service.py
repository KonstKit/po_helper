from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PullRequest, Task
from app.services.analytics_utils import DONE_STATUSES, as_float
from app.services.analytics.velocity_service import get_project_velocity

logger = logging.getLogger(__name__)


async def get_project_forecast(
    db: AsyncSession,
    project_id: int,
) -> Dict[str, Any]:
    try:
        velocity_data = await get_project_velocity(db=db, project_id=project_id, sprints_count=5)
        avg_velocity = as_float(velocity_data.get("average_velocity"))

        remaining_stmt = (
            select(func.sum(Task.estimate_hours))
            .where(Task.project_id == project_id)
            .where(func.lower(Task.status).notin_(list(DONE_STATUSES)))
        )
        remaining = as_float((await db.execute(remaining_stmt)).scalar())

        forecast = round(remaining / avg_velocity, 2) if avg_velocity > 0 else None
        return {
            "average_velocity": round(avg_velocity, 2),
            "remaining_hours": round(remaining, 2),
            "forecast_sprints": forecast,
        }
    except SQLAlchemyError as exc:
        logger.warning("forecast_completion(%s) failed: %s", project_id, exc)
        return {
            "average_velocity": 0.0,
            "remaining_hours": 0.0,
            "forecast_sprints": None,
            "error": "db_error",
        }


async def get_project_pr_forecast(
    db: AsyncSession,
    project_id: int,
) -> Dict[str, Any]:
    try:
        stmt = select(
            func.count(PullRequest.id).label("total"),
            func.avg(PullRequest.cycle_time_hours).label("avg_cycle"),
            func.avg(PullRequest.lead_time_hours).label("avg_lead"),
            func.avg(PullRequest.time_to_first_review_hours).label("avg_first_review"),
        ).where(PullRequest.repository_id == project_id)
        row = (await db.execute(stmt)).first()
        total = int(row.total or 0) if row and row.total is not None else 0
        avg_cycle = round(as_float(row.avg_cycle), 2) if row and row.avg_cycle is not None else 0.0
        avg_lead = round(as_float(row.avg_lead), 2) if row and row.avg_lead is not None else 0.0
        avg_first = (
            round(as_float(row.avg_first_review), 2)
            if row and row.avg_first_review is not None
            else 0.0
        )
        return {
            "total": total,
            "avg_cycle_time_hours": avg_cycle,
            "avg_lead_time_hours": avg_lead,
            "avg_time_to_first_review_hours": avg_first,
        }
    except SQLAlchemyError as exc:
        logger.warning("project_pr_forecast(%s) failed: %s", project_id, exc)
        return {
            "total": 0,
            "avg_cycle_time_hours": 0.0,
            "avg_lead_time_hours": 0.0,
            "avg_time_to_first_review_hours": 0.0,
            "error": "db_error",
        }
