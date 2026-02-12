from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Source, SyncState, SyncTask
from app.services.audit_log import record_audit_event


async def get_or_create_source(
    db: AsyncSession,
    provider: str,
    project_id: int | None = None,
    tenant_id: str | None = None,
    base_url: str | None = None,
    settings: dict[str, Any] | None = None,
) -> Source:
    filters: list[Any] = [Source.type == provider]
    if project_id is None:
        filters.append(Source.project_id.is_(None))
    else:
        filters.append(Source.project_id == project_id)
    if tenant_id is not None:
        filters.append(Source.tenant_id == tenant_id)

    result = await db.execute(select(Source).where(*filters))
    source = result.scalar_one_or_none()

    if source is None:
        source = Source(
            type=provider,
            project_id=project_id,
            tenant_id=tenant_id,
            base_url=base_url,
            settings=settings,
        )
        db.add(source)
        await db.flush()
        return source

    if base_url and source.base_url != base_url:
        source.base_url = base_url

    if settings:
        merged = dict(source.settings or {})
        for key, value in settings.items():
            if value is not None:
                merged[key] = value
        source.settings = merged

    return source


async def start_sync_task(
    db: AsyncSession,
    task_type: str,
    project_id: int | None = None,
    source_id: int | None = None,
    trigger: str | None = None,
    cursor_in: str | None = None,
    item_counts: dict[str, Any] | None = None,
) -> SyncTask:
    task = SyncTask(
        source_id=source_id,
        project_id=project_id,
        task_type=task_type,
        status="running",
        started_at=datetime.utcnow(),
        cursor_in=cursor_in,
        item_counts=item_counts,
        trigger=trigger,
    )
    db.add(task)
    await db.flush()
    await record_audit_event(
        db,
        action="sync_start",
        entity_type="sync_task",
        entity_id=task.id,
        project_id=task.project_id,
        payload={
            "task_type": task.task_type,
            "source_id": task.source_id,
            "trigger": task.trigger,
        },
    )
    return task


async def finish_sync_task(
    db: AsyncSession,
    task_id: int,
    status: str,
    item_counts: dict[str, Any] | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    cursor_out: str | None = None,
) -> Optional[SyncTask]:
    task = await db.get(SyncTask, task_id)
    if task is None:
        return None

    finished_at = datetime.utcnow()
    task.status = status
    task.finished_at = finished_at
    if task.started_at:
        task.duration_ms = int((finished_at - task.started_at).total_seconds() * 1000)

    if item_counts is not None:
        task.item_counts = item_counts
    if error_code is not None:
        task.error_code = error_code
    if error_message is not None:
        task.error_message = error_message
    if cursor_out is not None:
        task.cursor_out = cursor_out

    await record_audit_event(
        db,
        action="sync_finish",
        entity_type="sync_task",
        entity_id=task.id,
        project_id=task.project_id,
        outcome=status,
        payload={
            "status": status,
            "error_code": error_code,
        },
    )

    return task


async def upsert_sync_state(
    db: AsyncSession,
    source_id: int | None,
    project_id: int | None,
    last_cursor: str | None = None,
    last_event_id: str | None = None,
    lag_seconds: float | None = None,
    rate_limit_reset_at: datetime | None = None,
) -> SyncState:
    filters: list[Any] = []
    if source_id is None:
        filters.append(SyncState.source_id.is_(None))
    else:
        filters.append(SyncState.source_id == source_id)
    if project_id is None:
        filters.append(SyncState.project_id.is_(None))
    else:
        filters.append(SyncState.project_id == project_id)

    result = await db.execute(select(SyncState).where(*filters))
    state = result.scalar_one_or_none()

    if state is None:
        state = SyncState(source_id=source_id, project_id=project_id)
        db.add(state)

    if last_cursor is not None:
        state.last_cursor = last_cursor
    if last_event_id is not None:
        state.last_event_id = last_event_id
    if lag_seconds is not None:
        state.lag_seconds = lag_seconds
    if rate_limit_reset_at is not None:
        state.rate_limit_reset_at = rate_limit_reset_at

    return state
