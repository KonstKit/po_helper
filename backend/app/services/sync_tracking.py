from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.traceability import Source, SyncState, SyncTask
from app.services.audit_log import record_audit_event

STALE_RUNNING_ERROR_CODE = "stale_running_ttl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    # Keep write-path recovery as a protection when periodic cleanup is unavailable.
    await recover_stale_running_sync_tasks(db, project_id=project_id)

    started_at = _utcnow()
    task = SyncTask(
        source_id=source_id,
        project_id=project_id,
        task_type=task_type,
        status="running",
        started_at=started_at,
        heartbeat_at=started_at,
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


async def touch_sync_task_heartbeat(
    db: AsyncSession,
    task_id: int,
    item_counts: dict[str, Any] | None = None,
) -> Optional[SyncTask]:
    task = await db.get(SyncTask, task_id)
    if task is None or task.status != "running":
        return task

    task.heartbeat_at = _utcnow()
    if item_counts is not None:
        task.item_counts = item_counts
    return task


async def recover_stale_running_sync_tasks(
    db: AsyncSession,
    ttl_seconds: int | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
) -> int:
    effective_ttl = ttl_seconds
    if effective_ttl is None:
        effective_ttl = int(getattr(settings, "SYNC_TASK_RUNNING_TTL_SECONDS", 7200) or 7200)
    effective_ttl = max(1, int(effective_ttl))

    now_utc = _utcnow()
    stale_before = now_utc - timedelta(seconds=effective_ttl)

    filters = [
        SyncTask.status == "running",
        or_(
            SyncTask.heartbeat_at <= stale_before,
            (SyncTask.heartbeat_at.is_(None) & (SyncTask.started_at <= stale_before)),
        ),
    ]
    if project_id is not None:
        filters.append(SyncTask.project_id == project_id)
    if task_id is not None:
        filters.append(SyncTask.id == task_id)

    stmt = select(SyncTask).where(*filters)
    stale_tasks = list((await db.execute(stmt)).scalars().all())
    if not stale_tasks:
        return 0

    for task in stale_tasks:
        previous_heartbeat = _as_utc(task.heartbeat_at)
        started_at = _as_utc(task.started_at)
        task.status = "failed"
        task.finished_at = now_utc
        task.heartbeat_at = now_utc
        last_heartbeat = previous_heartbeat or started_at
        if started_at:
            task.duration_ms = int((now_utc - started_at).total_seconds() * 1000)

        task.error_code = STALE_RUNNING_ERROR_CODE
        heartbeat_str = last_heartbeat.isoformat() if last_heartbeat else "unknown"
        task.error_message = (
            f"Auto-failed stale running sync task: heartbeat exceeded TTL "
            f"({effective_ttl}s), last heartbeat={heartbeat_str}"
        )

        await record_audit_event(
            db,
            action="sync_recover_stale_running",
            entity_type="sync_task",
            entity_id=task.id,
            project_id=task.project_id,
            outcome="failed",
            payload={
                "status": task.status,
                "error_code": task.error_code,
                "ttl_seconds": effective_ttl,
            },
        )

    return len(stale_tasks)


async def get_fresh_running_sync_task(
    db: AsyncSession,
    task_type: str,
    project_id: int | None = None,
    freshness_seconds: int | None = None,
) -> Optional[SyncTask]:
    effective_freshness = freshness_seconds
    if effective_freshness is None:
        effective_freshness = int(
            getattr(settings, "SYNC_TASK_ACTIVE_HEARTBEAT_GRACE_SECONDS", 900) or 900
        )
    effective_freshness = max(1, int(effective_freshness))
    fresh_after = _utcnow() - timedelta(seconds=effective_freshness)

    stmt = (
        select(SyncTask)
        .where(SyncTask.status == "running", SyncTask.task_type == task_type)
        .where(
            or_(
                SyncTask.heartbeat_at >= fresh_after,
                (SyncTask.heartbeat_at.is_(None) & (SyncTask.started_at >= fresh_after)),
            )
        )
        .order_by(SyncTask.started_at.desc(), SyncTask.id.desc())
    )
    if project_id is not None:
        stmt = stmt.where(SyncTask.project_id == project_id)

    result = await db.execute(stmt)
    return result.scalars().first()


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

    finished_at = _utcnow()
    task.status = status
    task.finished_at = finished_at
    task.heartbeat_at = finished_at
    if task.started_at:
        started_at = _as_utc(task.started_at)
        if started_at:
            task.duration_ms = int((finished_at - started_at).total_seconds() * 1000)

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
