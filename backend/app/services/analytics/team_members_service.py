from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task

logger = logging.getLogger(__name__)


async def get_team_members_activity(
    db: AsyncSession,
    project_id: int,
) -> List[Dict[str, Any]]:
    """Get team members with their last activity dates."""
    try:
        done_statuses_set = {"done", "closed", "resolved", "complete"}
        active_statuses_set = {"in progress", "active", "doing"}

        team_stmt = (
            select(
                Task.assignee_name.label("name"),
                Task.assignee_email.label("email"),
                func.count(Task.id).label("total_tasks"),
                func.sum(
                    case(
                        (func.lower(Task.status).in_(list(done_statuses_set)), 1),
                        else_=0,
                    )
                ).label("completed_tasks"),
                func.sum(
                    case(
                        (func.lower(Task.status).in_(list(active_statuses_set)), 1),
                        else_=0,
                    )
                ).label("active_tasks"),
                func.max(Task.updated_date).label("last_activity"),
            )
            .where(Task.project_id == project_id)
            .where(or_(Task.assignee_email.is_not(None), Task.assignee_name.is_not(None)))
            .group_by(Task.assignee_email, Task.assignee_name)
        )

        team_rows = (await db.execute(team_stmt)).mappings().all()

        now = datetime.now()
        result: List[Dict[str, Any]] = []
        for row in team_rows:
            member = {
                "name": row["name"],
                "email": row["email"],
                "total_tasks": row["total_tasks"],
                "active_tasks": row["active_tasks"] or 0,
                "completed_tasks": row["completed_tasks"] or 0,
                "last_activity": None,
                "days_since_activity": None,
            }

            if row["last_activity"]:
                last_act = row["last_activity"]
                if hasattr(last_act, "tzinfo") and last_act.tzinfo is not None:
                    last_act = last_act.replace(tzinfo=None)

                delta = now - last_act
                days = delta.days
                if days < 0 and abs(delta.total_seconds()) < 86400:
                    days = 0
                member["days_since_activity"] = max(0, days)
                member["last_activity"] = row["last_activity"].isoformat()

            result.append(member)

        result.sort(key=lambda x: x["last_activity"] or "", reverse=True)

        return result
    except SQLAlchemyError as exc:
        logger.warning("get_team_members_activity error: %s", exc)
        return []
