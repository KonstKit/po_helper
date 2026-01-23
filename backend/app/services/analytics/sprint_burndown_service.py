from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.analytics_utils import compute_sprint_burndown

logger = logging.getLogger(__name__)


async def get_sprint_burndown(
    db: AsyncSession,
    sprint_id: int,
) -> Dict[str, Any]:
    try:
        data = await compute_sprint_burndown(db, sprint_id)
        return data
    except SQLAlchemyError as exc:
        logger.warning("sprint_burndown(%s) failed: %s", sprint_id, exc)
        return {"ideal_burndown": [], "actual_burndown": [], "error": "db_error"}
