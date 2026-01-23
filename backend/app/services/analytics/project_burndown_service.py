from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from sqlalchemy import case, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sprint
from app.services.analytics_utils import compute_sprint_burndown, fetch_sprint_meta

logger = logging.getLogger(__name__)


async def get_project_burndown(
    db: AsyncSession,
    project_id: int,
    sprint_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Get project burndown chart for a specified or latest sprint."""
    try:
        target_id = sprint_id
        sprint_meta: Optional[Dict[str, Any]] = None

        if target_id is None:
            priority = case(
                (Sprint.__table__.c.state == "active", 0),
                (Sprint.__table__.c.state == "future", 1),
                else_=2,
            )
            stmt = (
                select(Sprint.__table__.c.id)
                .where(Sprint.__table__.c.project_id == project_id)
                .order_by(priority, Sprint.__table__.c.start_date.desc())
                .limit(1)
            )
            row = (await db.execute(stmt)).first()
            target_id = row.id if row else None

        if not target_id:
            return {"sprint": None, "ideal_burndown": [], "actual_burndown": []}

        sprint_meta = await fetch_sprint_meta(db, target_id)
        data = await compute_sprint_burndown(db, target_id)
        data["sprint"] = sprint_meta
        return data
    except SQLAlchemyError as exc:
        logger.warning("project_burndown(%s) failed: %s", project_id, exc)
        return {"sprint": None, "ideal_burndown": [], "actual_burndown": [], "error": "db_error"}
