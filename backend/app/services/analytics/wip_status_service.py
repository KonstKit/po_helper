from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.analytics_utils import DONE_STATUSES

logger = logging.getLogger(__name__)


async def get_sprint_wip_status(
    db: AsyncSession,
    sprint_id: int,
) -> Dict[str, Any]:
    start = perf_counter()
    logger.info("analytics.sprint_wip.start sprint_id=%s", sprint_id)
    try:
        done_statuses = list(DONE_STATUSES)

        assignee_expr = func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned")

        aggregates_stmt = (
            select(
                assignee_expr.label("assignee"),
                func.count(Task.id).label("active_count"),
            )
            .where(Task.sprint_id == sprint_id)
            .where(func.lower(Task.status).notin_(done_statuses))
            .group_by(assignee_expr)
        )

        aggregates_rows = (await db.execute(aggregates_stmt)).mappings().all()
        total_active = sum(row["active_count"] for row in aggregates_rows)

        from app.core.config import settings as _settings

        limit_default = getattr(_settings, "WIP_LIMIT_PER_ASSIGNEE", 2) or 2
        overrides = getattr(_settings, "WIP_LIMIT_OVERRIDES", {}) or {}

        def eff_limit(assignee: str) -> int:
            override = overrides.get(assignee) or overrides.get((assignee or "").lower())
            try:
                if override is not None:
                    return int(override)
            except Exception:
                pass
            return limit_default

        assignees: List[Dict[str, Any]] = []
        for row in sorted(aggregates_rows, key=lambda r: (-r["active_count"], r["assignee"])):
            name = row["assignee"]
            count = row["active_count"]
            limit = eff_limit(name)
            assignees.append(
                {
                    "assignee": name,
                    "active_tasks": count,
                    "limit": limit,
                    "wip_exceeded": bool(count > limit),
                }
            )

        logger.info(
            "analytics.sprint_wip.success sprint_id=%s active=%s duration=%.3f",
            sprint_id,
            total_active,
            perf_counter() - start,
        )
        return {
            "total_active": total_active,
            "limit_default": limit_default,
            "assignees": assignees,
        }
    except SQLAlchemyError as exc:
        logger.warning(
            "analytics.sprint_wip.error sprint_id=%s duration=%.3f error=%s",
            sprint_id,
            perf_counter() - start,
            exc,
        )
        return {"total_active": 0, "limit_default": 2, "assignees": [], "error": "db_error"}
