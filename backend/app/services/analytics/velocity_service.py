from __future__ import annotations

import logging
from time import perf_counter
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sprint, Task
from app.services.analytics_utils import DONE_STATUSES, as_float

logger = logging.getLogger(__name__)


async def get_project_velocity(
    db: AsyncSession,
    project_id: int,
    sprints_count: int = 5,
) -> Dict[str, Any]:
    """Compute project velocity metrics with a single grouped query."""
    start = perf_counter()
    logger.info(
        "analytics.project_velocity.start project_id=%s sprints_count=%s",
        project_id,
        sprints_count,
    )
    try:
        limit = max(1, int(sprints_count or 5))
        stmt = (
            select(
                Sprint.__table__.c.id.label("id"),
                Sprint.__table__.c.name.label("name"),
                Sprint.__table__.c.end_date.label("end_date"),
            )
            .where(Sprint.__table__.c.project_id == project_id)
            .where(Sprint.__table__.c.state == "closed")
            .order_by(Sprint.__table__.c.end_date.desc())
            .limit(limit)
        )
        sprint_rows = (await db.execute(stmt)).mappings().all()
        if not sprint_rows:
            duration = perf_counter() - start
            logger.info(
                "analytics.project_velocity.empty project_id=%s duration=%.3f",
                project_id,
                duration,
            )
            return {
                "average_velocity": 0.0,
                "sprints_analyzed": 0,
                "velocity_trend": "insufficient_data",
                "sprint_velocities": [],
            }

        sprint_ids = [row["id"] for row in sprint_rows]
        done_statuses = list(DONE_STATUSES)

        velocity_stmt = (
            select(
                Task.sprint_id,
                func.sum(Task.estimate_hours).label("completed_hours"),
            )
            .where(Task.sprint_id.in_(sprint_ids))
            .where(func.lower(Task.status).in_(done_statuses))
            .group_by(Task.sprint_id)
        )
        velocity_rows = (await db.execute(velocity_stmt)).mappings().all()

        velocity_by_sprint = {
            row["sprint_id"]: as_float(row["completed_hours"]) for row in velocity_rows
        }

        velocities: List[Dict[str, Any]] = []
        for row in sprint_rows:
            completed = velocity_by_sprint.get(row["id"], 0.0)
            velocities.append(
                {
                    "sprint_id": row["id"],
                    "sprint_name": row["name"],
                    "velocity": round(completed, 2),
                    "end_date": row["end_date"],
                }
            )

        avg_velocity = sum(v["velocity"] for v in velocities) / max(1, len(velocities))
        trend = "insufficient_data"
        if len(velocities) >= 4:
            recent = sum(v["velocity"] for v in velocities[:2]) / 2
            older = sum(v["velocity"] for v in velocities[2:4]) / 2
            if recent > older * 1.1:
                trend = "increasing"
            elif recent < older * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"

        response = {
            "average_velocity": round(avg_velocity, 2),
            "sprints_analyzed": len(velocities),
            "velocity_trend": trend,
            "sprint_velocities": velocities,
        }
        duration = perf_counter() - start
        logger.info(
            "analytics.project_velocity.success project_id=%s sprints=%s avg=%.2f duration=%.3f",
            project_id,
            len(velocities),
            response["average_velocity"],
            duration,
        )
        return response
    except Exception:
        logger.exception(
            "analytics.project_velocity.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise
