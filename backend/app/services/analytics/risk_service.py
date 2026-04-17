from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import DONE_STATUSES, as_float

logger = logging.getLogger(__name__)


async def get_project_risks(
    db: AsyncSession,
    project_id: int,
) -> Dict[str, Any]:
    try:
        now = datetime.now(timezone.utc)
        done_statuses = list(DONE_STATUSES)
        risks: List[Dict[str, Any]] = []

        overdue_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.due_date.is_not(None))
            .where(Task.due_date < now)
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        overdue_count = (await db.execute(overdue_count_stmt)).scalar() or 0

        if overdue_count > 0:
            overdue_tasks_stmt = (
                select(Task.key, Task.summary)
                .where(Task.project_id == project_id)
                .where(Task.due_date.is_not(None))
                .where(Task.due_date < now)
                .where(func.lower(Task.status).notin_(done_statuses))
                .limit(5)
            )
            overdue_tasks = (await db.execute(overdue_tasks_stmt)).mappings().all()

            risks.append(
                {
                    "type": "overdue_tasks",
                    "severity": "high" if overdue_count > 5 else "medium",
                    "count": overdue_count,
                    "tasks": [{"key": t["key"], "summary": t["summary"]} for t in overdue_tasks],
                }
            )

        blocked_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.is_blocker)
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        blocked_count = (await db.execute(blocked_count_stmt)).scalar() or 0

        if blocked_count > 0:
            blocked_tasks_stmt = (
                select(Task.key, Task.summary)
                .where(Task.project_id == project_id)
                .where(Task.is_blocker)
                .where(func.lower(Task.status).notin_(done_statuses))
                .limit(5)
            )
            blocked_tasks = (await db.execute(blocked_tasks_stmt)).mappings().all()

            risks.append(
                {
                    "type": "blocked_tasks",
                    "severity": "high",
                    "count": blocked_count,
                    "tasks": [{"key": t["key"], "summary": t["summary"]} for t in blocked_tasks],
                }
            )

        unestimated_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_(None))
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        unestimated_count = (await db.execute(unestimated_count_stmt)).scalar() or 0

        if unestimated_count > 3:
            risks.append(
                {
                    "type": "unestimated_tasks",
                    "severity": "medium",
                    "count": unestimated_count,
                }
            )

        overrun_stmt = (
            select(
                func.count(Task.id).label("count"),
                func.sum(Task.spent_hours - Task.estimate_hours).label("total_overrun"),
            )
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_not(None))
            .where(Task.spent_hours > Task.estimate_hours)
        )
        overrun_result = (await db.execute(overrun_stmt)).mappings().first()
        if overrun_result is None:
            overrun_count = 0
            total_overrun = 0.0
        else:
            overrun_count = int(overrun_result.get("count") or 0)
            total_overrun = as_float(overrun_result.get("total_overrun"))

        if overrun_count > 0:
            risks.append(
                {
                    "type": "budget_overrun",
                    "severity": "high" if total_overrun > 40 else "medium",
                    "count": overrun_count,
                    "total_overrun_hours": round(total_overrun, 2),
                }
            )

        risk_score = sum(
            3 if r.get("severity") == "high" else 2 if r.get("severity") == "medium" else 1
            for r in risks
        )
        risk_level = (
            "critical"
            if risk_score > 9
            else "high"
            if risk_score > 6
            else "medium"
            if risk_score > 3
            else "low"
        )
        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "total_risks": len(risks),
            "risks": risks,
        }
    except SQLAlchemyError as exc:
        logger.warning("identify_project_risks(%s) failed: %s", project_id, exc)
        return {
            "risk_level": "unknown",
            "risk_score": 0,
            "total_risks": 0,
            "risks": [],
            "error": "db_error",
        }
