from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.models.capacity import CapacitySettings
from app.services.analytics_utils import as_float, fetch_sprint_meta

logger = logging.getLogger(__name__)


async def get_sprint_capacity(
    db: AsyncSession,
    sprint_id: int,
) -> Dict[str, Any]:
    try:
        sprint = await fetch_sprint_meta(db, sprint_id)
        if not sprint:
            return {
                "sprint_id": sprint_id,
                "weeks": 1,
                "capacity_hours_per_person": 40.0,
                "total_planned_hours": 0.0,
                "total_effective_capacity": 0.0,
                "assignees": [],
            }

        project_id = sprint.get("project_id")
        start = sprint.get("start_date")
        end = sprint.get("end_date")
        duration_days = max(1, ((end or start) - start).days) if (start and end) else 7
        weeks = max(1.0, round(duration_days / 7.0, 2))

        assignee_expr = func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned")
        planned_stmt = (
            select(
                assignee_expr.label("assignee"),
                Task.assignee_email.label("email"),
                func.coalesce(func.sum(Task.estimate_hours), 0.0).label("planned_hours"),
            )
            .where(Task.sprint_id == sprint_id)
            .group_by(
                assignee_expr,
                Task.assignee_email,
            )
        )
        planned_rows = (await db.execute(planned_stmt)).mappings().all()

        assignee_emails = [row["email"] for row in planned_rows if row["email"]]

        capacity_map: Dict[str, Any] = {}
        if assignee_emails:
            from datetime import date

            today = date.today()
            cap_stmt = (
                select(CapacitySettings)
                .where(
                    and_(
                        CapacitySettings.assignee_email.in_(assignee_emails),
                        or_(
                            CapacitySettings.project_id == project_id,
                            CapacitySettings.project_id.is_(None),
                        ),
                        or_(
                            CapacitySettings.valid_from.is_(None),
                            CapacitySettings.valid_from <= today,
                        ),
                        or_(
                            CapacitySettings.valid_to.is_(None),
                            CapacitySettings.valid_to >= today,
                        ),
                    )
                )
                .order_by(CapacitySettings.project_id.is_(None).asc())
            )

            cap_result = await db.execute(cap_stmt)
            for setting in cap_result.scalars().all():
                if setting.assignee_email not in capacity_map:
                    capacity_map[setting.assignee_email] = (
                        setting.hours_per_week,
                        setting.focus_factor,
                    )

        assignees: List[Dict[str, Any]] = []
        total_planned = 0.0
        total_effective_capacity = 0.0
        default_capacity_per_person = round(40.0 * weeks, 2)

        for row in sorted(planned_rows, key=lambda r: r["assignee"]):
            name = row["assignee"]
            email = row["email"]
            hours = as_float(row["planned_hours"])
            total_planned += hours

            hours_per_week, focus_factor = capacity_map.get(email, (40.0, 0.8))

            theoretical_capacity = round(hours_per_week * weeks, 2)
            effective_capacity = round(theoretical_capacity * focus_factor, 2)
            total_effective_capacity += effective_capacity

            utilization = (hours / effective_capacity * 100.0) if effective_capacity else 0.0

            assignees.append(
                {
                    "assignee": name,
                    "assignee_email": email,
                    "planned_hours": round(hours, 2),
                    "capacity_hours": theoretical_capacity,
                    "effective_capacity": effective_capacity,
                    "focus_factor": focus_factor,
                    "utilization_pct": round(utilization, 2),
                    "has_custom_settings": email in capacity_map,
                }
            )

        return {
            "sprint_id": sprint_id,
            "project_id": project_id,
            "weeks": weeks,
            "capacity_hours_per_person": default_capacity_per_person,
            "total_planned_hours": round(total_planned, 2),
            "total_effective_capacity": round(total_effective_capacity, 2),
            "assignees": assignees,
        }
    except SQLAlchemyError as exc:
        logger.warning("sprint_capacity(%s) failed: %s", sprint_id, exc)
        return {
            "sprint_id": sprint_id,
            "weeks": 1,
            "capacity_hours_per_person": 40.0,
            "total_planned_hours": 0.0,
            "total_effective_capacity": 0.0,
            "assignees": [],
            "error": "db_error",
        }
