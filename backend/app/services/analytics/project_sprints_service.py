from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sprint
from app.services.jira_service import jira_service
from app.utils import parse_datetime

logger = logging.getLogger(__name__)


def _build_sprints_stmt(project_id: int, limit: int):
    return (
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


def _rows_to_sprints(rows: Any) -> list[Dict[str, Any]]:
    sprints: list[Dict[str, Any]] = []
    for row in rows.mappings():
        sprint = dict(row)
        sprint["id"] = sprint.get("sprint_id")
        sprints.append(sprint)
    return sprints


async def _fetch_sprints_from_db(db: AsyncSession, project_id: int, limit: int) -> list[Dict[str, Any]]:
    rows = await asyncio.wait_for(db.execute(_build_sprints_stmt(project_id, limit)), timeout=30.0)
    return _rows_to_sprints(rows)


async def _backfill_sprints_from_board(
    db: AsyncSession,
    project_id: int,
    board_id: int,
) -> int:
    """Load sprints from Jira board and persist metadata locally for analytics dropdown."""
    try:
        jira_sprints = await asyncio.to_thread(jira_service.list_sprints, board_id)
    except Exception as exc:
        logger.warning(
            "analytics.project_sprints.jira_fetch_failed project_id=%s board_id=%s error=%s",
            project_id,
            board_id,
            exc,
        )
        return 0

    if not jira_sprints:
        return 0

    synced = 0
    try:
        for sprint in jira_sprints:
            jira_id = sprint.get("id")
            if jira_id is None:
                continue

            jira_id_str = str(jira_id)
            db_sprint = (
                await db.execute(select(Sprint).where(Sprint.jira_id == jira_id_str))
            ).scalar_one_or_none()

            if not db_sprint:
                db_sprint = Sprint(jira_id=jira_id_str, name=f"Sprint {jira_id}")
                db.add(db_sprint)

            db_sprint.project_id = project_id
            db_sprint.name = str(sprint.get("name") or f"Sprint {jira_id}")
            db_sprint.state = sprint.get("state")
            db_sprint.goal = sprint.get("goal")
            db_sprint.start_date = parse_datetime(sprint.get("startDate"))
            db_sprint.end_date = parse_datetime(sprint.get("endDate"))
            db_sprint.complete_date = parse_datetime(sprint.get("completeDate"))
            synced += 1

        await db.commit()
        return synced
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.warning(
            "analytics.project_sprints.jira_backfill_db_error project_id=%s board_id=%s error=%s",
            project_id,
            board_id,
            exc,
        )
        return 0


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
        cached_total = int(cached_result.get("total") or 0)
        # Do not trust cached empty results when board is explicitly chosen:
        # user may switch from Kanban to Scrum and expect fresh sprint discovery.
        if cached_total > 0 or board_id is None:
            logger.info("analytics.project_sprints.cache_hit project_id=%s", project_id)
            return cached_result

    try:
        try:
            sprints = await _fetch_sprints_from_db(db, project_id, limit)

            if not sprints and isinstance(board_id, int):
                logger.info(
                    "analytics.project_sprints.empty_local_fallback project_id=%s board_id=%s",
                    project_id,
                    board_id,
                )
                synced = await _backfill_sprints_from_board(db, project_id, board_id)
                if synced > 0:
                    sprints = await _fetch_sprints_from_db(db, project_id, limit)

            result = {
                "total": len(sprints),
                "board_id": board_id,
                "sprints": sprints,
            }

            cache_service.set(cache_key, result, ttl=300 if sprints else 60)

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
