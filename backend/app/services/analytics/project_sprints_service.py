from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sprint

logger = logging.getLogger(__name__)


async def get_project_sprints(
    db: AsyncSession,
    project_id: int,
    limit: int = 10,
    board_id: Optional[int] = None,
) -> Dict[str, Any]:
    start = perf_counter()
    logger.info(
        "analytics.project_sprints.start project_id=%s limit=%s board_id=%s",
        project_id,
        limit,
        board_id,
    )

    from app.services.cache_service import cache_service

    cache_key = cache_service._make_key("project_sprints", project_id, limit, board_id)
    cached_result = cache_service.get(cache_key)
    if cached_result:
        logger.info("analytics.project_sprints.cache_hit project_id=%s", project_id)
        return cached_result

    try:
        stmt = (
            select(
                Sprint.id.label("sprint_id"),
                Sprint.name,
                Sprint.state,
                Sprint.goal,
                Sprint.start_date,
                Sprint.end_date,
                Sprint.complete_date,
                Sprint.velocity,
                Sprint.commitment,
                Sprint.completed,
            )
            .where(Sprint.project_id == project_id)
            .order_by(Sprint.start_date.desc().nullslast())
            .limit(limit)
        )

        try:
            rows = await asyncio.wait_for(db.execute(stmt), timeout=30.0)
            sprints = []
            for row in rows.mappings():
                sprint = dict(row)
                sprint["id"] = sprint.get("sprint_id")
                sprints.append(sprint)

            result = {
                "total": len(sprints),
                "board_id": board_id,
                "sprints": sprints,
            }

            cache_service.set(cache_key, result, ttl=300)

            logger.info(
                "analytics.project_sprints.success project_id=%s count=%s duration=%.3f",
                project_id,
                len(sprints),
                perf_counter() - start,
            )
            return result
        except asyncio.TimeoutError:
            logger.error(
                "analytics.project_sprints.timeout project_id=%s duration=%.3f",
                project_id,
                perf_counter() - start,
            )
            empty_result: Dict[str, Any] = {
                "total": 0,
                "board_id": board_id,
                "sprints": [],
                "error": "timeout",
            }
            cache_service.set(cache_key, empty_result, ttl=60)
            return empty_result
    except SQLAlchemyError as exc:
        logger.warning(
            "analytics.project_sprints.error project_id=%s duration=%.3f error=%s",
            project_id,
            perf_counter() - start,
            exc,
        )
        return {"total": 0, "board_id": board_id, "sprints": [], "error": "db_error"}
