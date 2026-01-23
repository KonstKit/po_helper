from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import DONE_STATUSES

logger = logging.getLogger(__name__)


async def get_sprint_quality(
    db: AsyncSession,
    sprint_id: int,
) -> Dict[str, Any]:
    try:
        done_statuses = list(DONE_STATUSES)

        counts_stmt = select(
            func.count(Task.id).label("total"),
            func.sum(case((func.lower(Task.status).in_(done_statuses), 1), else_=0)).label("done"),
            func.sum(case((Task.is_blocker, 1), else_=0)).label("blockers"),
        ).where(Task.sprint_id == sprint_id)
        counts = (await db.execute(counts_stmt)).mappings().first()

        total = counts["total"] or 0
        done = counts["done"] or 0
        blockers = counts["blockers"] or 0

        bugs_stmt = (
            select(
                func.coalesce(Task.priority, "Unspecified").label("priority"),
                func.count(Task.id).label("bug_count"),
            )
            .where(Task.sprint_id == sprint_id)
            .where(func.lower(Task.task_type) == "bug")
            .group_by(func.coalesce(Task.priority, "Unspecified"))
        )
        bugs_rows = (await db.execute(bugs_stmt)).mappings().all()
        bugs = {row["priority"]: row["bug_count"] for row in bugs_rows}

        dod_pct = (done / total * 100.0) if total else 0.0
        return {
            "total_tasks": total,
            "dod_pct": round(dod_pct, 2),
            "bugs_by_priority": bugs,
            "blockers": blockers,
        }
    except SQLAlchemyError as exc:
        logger.warning("sprint_quality(%s) failed: %s", sprint_id, exc)
        return {
            "total_tasks": 0,
            "dod_pct": 0.0,
            "bugs_by_priority": {},
            "blockers": 0,
            "error": "db_error",
        }
