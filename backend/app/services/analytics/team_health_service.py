from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import and_, case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import as_float

logger = logging.getLogger(__name__)


async def get_project_team_health(
    db: AsyncSession,
    project_id: int,
) -> Dict[str, Any]:
    """Compute team health metrics using aggregate queries."""
    try:
        done_statuses_set = {"done", "closed", "resolved", "complete"}
        in_progress_statuses_set = {"in progress", "active", "doing"}
        now = datetime.now(timezone.utc)

        counts_stmt = select(
            func.count(Task.id).label("total"),
            func.sum(
                case(
                    (func.lower(Task.status).in_(list(done_statuses_set)), 1),
                    else_=0,
                )
            ).label("done"),
            func.sum(
                case(
                    (func.lower(Task.status).in_(list(in_progress_statuses_set)), 1),
                    else_=0,
                )
            ).label("in_progress"),
            func.sum(case((Task.is_blocker, 1), else_=0)).label("blockers"),
            func.sum(
                case(
                    (
                        and_(
                            Task.due_date.is_not(None),
                            Task.due_date < now,
                            func.lower(Task.status).notin_(list(done_statuses_set)),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("overdue"),
            func.coalesce(func.sum(Task.estimate_hours), 0.0).label("estimate_hours"),
            func.coalesce(func.sum(Task.spent_hours), 0.0).label("spent_hours"),
        ).where(Task.project_id == project_id)
        counts = (await db.execute(counts_stmt)).mappings().first()

        total = counts["total"] or 0
        if total == 0:
            return {
                "total": 0,
                "done": 0,
                "in_progress": 0,
                "backlog": 0,
                "blockers": 0,
                "overdue": 0,
                "completion_rate": 0.0,
                "estimate_hours": 0.0,
                "spent_hours": 0.0,
                "avg_cycle_time_hours": None,
                "median_cycle_time_hours": None,
                "cycle_samples": 0,
            }

        done = counts["done"] or 0
        in_progress = counts["in_progress"] or 0
        backlog = total - done - in_progress
        blockers = counts["blockers"] or 0
        overdue = counts["overdue"] or 0
        estimate_hours = as_float(counts["estimate_hours"])
        spent_hours = as_float(counts["spent_hours"])

        cycle_stmt = (
            select(
                func.extract("epoch", Task.resolved_date - Task.created_date).label("cycle_seconds")
            )
            .where(Task.project_id == project_id)
            .where(func.lower(Task.status).in_(list(done_statuses_set)))
            .where(Task.created_date.is_not(None))
            .where(Task.resolved_date.is_not(None))
        )
        cycle_rows = (await db.execute(cycle_stmt)).scalars().all()
        cycle_times = [float(seconds) / 3600.0 for seconds in cycle_rows if seconds is not None]

        completion_rate = (done / total) if total else 0.0
        avg_cycle = statistics.mean(cycle_times) if cycle_times else None
        median_cycle = statistics.median(cycle_times) if cycle_times else None

        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "backlog": backlog,
            "blockers": blockers,
            "overdue": overdue,
            "completion_rate": round(completion_rate, 4),
            "estimate_hours": round(estimate_hours, 2),
            "spent_hours": round(spent_hours, 2),
            "avg_cycle_time_hours": round(avg_cycle, 2) if avg_cycle is not None else None,
            "median_cycle_time_hours": round(median_cycle, 2) if median_cycle is not None else None,
            "cycle_samples": len(cycle_times),
        }
    except SQLAlchemyError as exc:
        logger.warning("analytics.team_health.error project_id=%s error=%s", project_id, exc)
        return {
            "total": 0,
            "done": 0,
            "in_progress": 0,
            "backlog": 0,
            "blockers": 0,
            "overdue": 0,
            "completion_rate": 0.0,
            "estimate_hours": 0.0,
            "spent_hours": 0.0,
            "avg_cycle_time_hours": None,
            "median_cycle_time_hours": None,
            "cycle_samples": 0,
            "error": "db_error",
        }
