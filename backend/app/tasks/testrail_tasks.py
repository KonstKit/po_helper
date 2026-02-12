"""
Celery tasks for TestRail sync and linking.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any, Optional

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.traceability import ConnectorConfig
from app.services.testrail.linker import TestRailLinker
from app.services.testrail.sync import DEFAULT_LOOKBACK_DAYS
from app.services.testrail.sync_orchestrator import TestRailSyncOrchestrator

logger = logging.getLogger(__name__)


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_suite_ids(settings: dict[str, Any]) -> Optional[list[int]]:
    raw = settings.get("testrail_suite_ids") or settings.get("suite_ids")
    if raw is None:
        return None
    if isinstance(raw, list):
        values = raw
    else:
        values = [val.strip() for val in str(raw).split(",")]
    ids = [_as_int(val) for val in values]
    parsed = [val for val in ids if val is not None]
    return parsed or None


@celery_app.task(name="testrail.sync_project")
def sync_testrail_project(
    project_id: Optional[int],
    testrail_project_id: Optional[int] = None,
    suite_ids: Optional[list[int]] = None,
    cursor: Optional[int] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    link_after: bool = False,
    trigger: Optional[str] = "manual",
) -> dict[str, Any]:
    """Sync TestRail artifacts for a project, optionally linking them."""

    async def _run() -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            orchestrator = TestRailSyncOrchestrator()
            sync_result = await orchestrator.sync_project(
                db,
                project_id=project_id,
                testrail_project_id=testrail_project_id,
                suite_ids=suite_ids,
                cursor=cursor,
                lookback_days=lookback_days,
                trigger=trigger,
            )
            payload: dict[str, Any] = {"status": "ok", "sync": asdict(sync_result)}

            if link_after:
                try:
                    linker = await TestRailLinker.from_settings(db, project_id)
                    link_result = await linker.link_project(db, project_id=project_id)
                    payload["links"] = asdict(link_result)
                except Exception as exc:
                    logger.warning("TestRail link step failed: %s", exc)
                    payload["links_error"] = str(exc)

            return payload

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("TestRail sync task failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@celery_app.task(name="testrail.scheduled_sync")
def scheduled_testrail_sync() -> dict[str, Any]:
    """Scheduled task to sync all enabled TestRail connector configs."""
    logger.info("Running scheduled TestRail sync")

    async def _load_configs() -> list[ConnectorConfig]:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(ConnectorConfig)
                .where(
                    ConnectorConfig.provider == "testrail",
                    ConnectorConfig.is_enabled.is_(True),
                )
                .order_by(ConnectorConfig.created_at.desc())
            )
            rows = (await db.execute(stmt)).scalars().all()
            seen: set[int] = set()
            configs: list[ConnectorConfig] = []
            for row in rows:
                if row.project_id is None or row.project_id in seen:
                    continue
                configs.append(row)
                seen.add(row.project_id)
            return configs

    configs: list[ConnectorConfig] = []
    try:
        configs = asyncio.run(_load_configs())
    except Exception as exc:
        logger.error("Scheduled TestRail config load failed: %s", exc)
        return {"status": "error", "message": str(exc), "dispatched": 0, "skipped_configs": 0}

    if not configs:
        logger.info("No enabled TestRail connector configs; skipping scheduled sync")
        return {"status": "skipped", "dispatched": 0, "skipped_configs": 0}

    dispatched = 0
    skipped = 0
    for config in configs:
        settings = config.settings_json or {}
        testrail_project_id = _as_int(settings.get("testrail_project_id"))
        if testrail_project_id is None:
            skipped += 1
            continue

        suite_ids = _parse_suite_ids(settings)
        sync_testrail_project.delay(
            config.project_id,
            testrail_project_id,
            suite_ids,
            None,
            DEFAULT_LOOKBACK_DAYS,
            True,
            "schedule",
        )
        dispatched += 1

    logger.info(
        "Scheduled TestRail sync dispatched: %d project(s), %d skipped",
        dispatched,
        skipped,
    )
    return {"status": "ok", "dispatched": dispatched, "skipped_configs": skipped}
