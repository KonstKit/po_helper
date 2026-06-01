from __future__ import annotations

from dataclasses import asdict
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.settings import IntegrationSetting
from app.models.traceability import Source, SyncState
from app.services.integration_config import get_connector_overrides
from app.services.testrail.linker import TestRailLinker
from app.services.testrail.sync import DEFAULT_LOOKBACK_DAYS, TestRailSyncService
from app.services.testrail.sync_orchestrator import TestRailSyncOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_client(db: AsyncSession, project_id: Optional[int]) -> TestRailSyncService:
    try:
        service, _ = await TestRailSyncService.from_settings(db, project_id)
        return service
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
async def testrail_status(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == "testrail"))
    ).scalar_one_or_none()
    overrides = await get_connector_overrides(db, project_id, "testrail")
    override_settings = overrides.settings if overrides else {}

    base_url = override_settings.get("base_url") or (row.base_url if row and row.base_url else None)
    has_token = bool(
        override_settings.get("api_token")
        or override_settings.get("token")
        or (row and row.api_token)
    )

    source_stmt = select(Source).where(Source.type == "testrail")
    if project_id is None:
        source_stmt = source_stmt.where(Source.project_id.is_(None))
    else:
        source_stmt = source_stmt.where(Source.project_id == project_id)
    source = (await db.execute(source_stmt)).scalar_one_or_none()

    sync_state = None
    if source:
        state_stmt = select(SyncState).where(SyncState.source_id == source.id)
        sync_state = (await db.execute(state_stmt)).scalar_one_or_none()

    return {
        "configured": bool(base_url and has_token),
        "base_url": base_url,
        "has_token": has_token,
        "project_id": project_id,
        "last_cursor": sync_state.last_cursor if sync_state else None,
        "last_event_id": sync_state.last_event_id if sync_state else None,
        "lag_seconds": sync_state.lag_seconds if sync_state else None,
    }


@router.get("/projects")
async def list_testrail_projects(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    service = await _get_client(db, project_id)
    projects = await service.client.get_projects()
    return {"count": len(projects), "results": projects}


@router.get("/runs")
async def list_testrail_runs(
    testrail_project_id: int = Query(..., description="TestRail project ID"),
    project_id: Optional[int] = Query(default=None),
    include_completed: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
):
    service = await _get_client(db, project_id)
    runs = await service.client.get_runs(
        testrail_project_id, is_completed=None if include_completed else False
    )
    return {"count": len(runs), "results": runs}


@router.post("/sync")
async def sync_testrail(
    testrail_project_id: int = Query(..., description="TestRail project ID"),
    project_id: Optional[int] = Query(default=None, description="Internal project ID"),
    cursor: Optional[int] = Query(default=None, description="Unix timestamp cursor"),
    lookback_days: int = Query(default=DEFAULT_LOOKBACK_DAYS, ge=1),
    link: bool = Query(default=False, description="Link TestRail artifacts after sync"),
    db: AsyncSession = Depends(get_db),
):
    use_celery = getattr(settings, "CELERY_ENABLED", False)
    if use_celery and getattr(settings, "is_development", False):
        if not getattr(settings, "CELERY_USE_IN_DEV", True):
            use_celery = False

    if use_celery:
        try:
            from app.tasks.testrail_tasks import sync_testrail_project

            task = sync_testrail_project.delay(
                project_id,
                testrail_project_id,
                None,
                cursor,
                lookback_days,
                link,
                "manual",
            )
            return {
                "status": "syncing",
                "task_id": task.id,
                "project_id": project_id,
                "testrail_project_id": testrail_project_id,
                "link": link,
                "method": "celery",
            }
        except Exception as exc:
            logger.warning("Celery dispatch failed; falling back to in-process sync: %s", exc)

    orchestrator = TestRailSyncOrchestrator()
    result = await orchestrator.sync_project(
        db,
        project_id=project_id,
        testrail_project_id=testrail_project_id,
        cursor=cursor,
        lookback_days=lookback_days,
        trigger="manual",
    )
    payload: dict = {"sync": asdict(result)}

    if link:
        try:
            linker = await TestRailLinker.from_settings(db, project_id)
            link_result = await linker.link_project(db, project_id=project_id)
            payload["link"] = asdict(link_result)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("TestRail link step failed: %s", exc)
            payload["link_error"] = str(exc)

    return payload


@router.post("/link")
async def link_testrail(
    project_id: Optional[int] = Query(default=None, description="Internal project ID"),
    db: AsyncSession = Depends(get_db),
):
    try:
        linker = await TestRailLinker.from_settings(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = await linker.link_project(db, project_id=project_id)
    return asdict(result)
