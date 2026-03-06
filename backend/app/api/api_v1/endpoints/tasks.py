import asyncio
from io import BytesIO
import logging
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.exc import IntegrityError
from app.core.database import AsyncSessionLocal, get_db
from app.models import Task, BusinessValueAudit, User, Permissions
from app.schemas.task import Task as TaskSchema, TaskCreate, TaskUpdate, TaskWithRelations
from app.schemas.pagination import paginated_response
from app.api.deps import require_permission
from app.services.task_manager import task_manager
from app.utils import (
    transactional_session,
    handle_api_error,
    get_or_404,
    execute_with_lock,
)
from app.utils.error_handling import async_handle_api_error
from app.utils.batch_operations import bulk_delete_by_ids, bulk_update_by_ids
from app.core.cache_enhanced import CacheInvalidator

router = APIRouter()
logger = logging.getLogger(__name__)
TASK_EXPORT_COLUMNS = [
    "Key",
    "Summary",
    "Type",
    "Status",
    "Priority",
    "Assignee",
    "Estimate (hours)",
    "Spent (hours)",
    "Remaining (hours)",
    "Created",
    "Due Date",
]
TASK_EXPORT_DIR = Path(__file__).resolve().parents[4] / "exports" / "task_exports"


async def _load_tasks_for_export(
    project_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
) -> list[Task]:
    async with AsyncSessionLocal() as session:
        query = select(Task).order_by(Task.id)
        if project_id:
            query = query.where(Task.project_id == project_id)
        if sprint_id:
            query = query.where(Task.sprint_id == sprint_id)
        result = await session.execute(query)
        return list(result.scalars().all())


def _task_export_rows(tasks: list[Task]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for task in tasks:
        rows.append(
            {
                "Key": task.key,
                "Summary": task.summary,
                "Type": task.task_type,
                "Status": task.status,
                "Priority": task.priority,
                "Assignee": task.assignee_name,
                "Estimate (hours)": task.estimate_hours,
                "Spent (hours)": task.spent_hours,
                "Remaining (hours)": task.remaining_hours,
                "Created": task.created_date,
                "Due Date": task.due_date,
            }
        )
    return rows


def _render_tasks_excel(rows: list[dict[str, Any]]) -> BytesIO:
    df = pd.DataFrame(rows, columns=TASK_EXPORT_COLUMNS)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, sheet_name="Tasks", index=False)

        workbook = writer.book
        worksheet = writer.sheets["Tasks"]
        header_format = workbook.add_format(
            {"bold": True, "bg_color": "#4472C4", "font_color": "white", "border": 1}
        )

        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)

        for i, col in enumerate(df.columns):
            series = df[col].astype(str) if not df.empty else pd.Series([col])
            column_width = max(series.map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, min(column_width, 50))

    output.seek(0)
    return output


def _task_export_path(task_id: str) -> Path:
    TASK_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return TASK_EXPORT_DIR / f"tasks_export_{task_id}.xlsx"


def _write_tasks_excel_file(rows: list[dict[str, Any]], export_path: Path) -> None:
    export_path.write_bytes(_render_tasks_excel(rows).getvalue())


async def _build_task_export_result(
    project_id: Optional[int],
    sprint_id: Optional[int],
    task_id: str,
    task_manager,
) -> dict[str, Any]:
    task_manager.update_progress(task_id, 10.0, "Loading tasks")
    tasks = await _load_tasks_for_export(project_id=project_id, sprint_id=sprint_id)
    rows = _task_export_rows(tasks)
    task_manager.update_progress(task_id, 55.0, f"Preparing {len(rows)} tasks for export")

    export_path = _task_export_path(task_id)
    await asyncio.to_thread(_write_tasks_excel_file, rows, export_path)
    task_manager.update_progress(task_id, 95.0, "Finalizing export")

    return {
        "download_url": f"/api/v1/tasks/exports/{task_id}/download",
        "filename": export_path.name,
        "task_count": len(rows),
        "project_id": project_id,
        "sprint_id": sprint_id,
    }


async def _run_task_export_job(task_id: str, project_id: Optional[int], sprint_id: Optional[int]) -> None:
    try:
        await task_manager.run_async(
            task_id,
            _build_task_export_result,
            project_id=project_id,
            sprint_id=sprint_id,
        )
    except Exception:
        logger.exception("tasks.export.async.error task_id=%s", task_id)


@router.get("/")
async def get_tasks(
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    sprint_id: Optional[int] = Query(None, description="Filter by sprint ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    assignee: Optional[str] = Query(None, description="Filter by assignee email"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=1000, description="Max records to return"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_VIEW)),
) -> Dict[str, Any]:
    """
    Get paginated tasks with filters.

    Returns paginated response with metadata:
    - data: list of tasks
    - meta: pagination info (total, page, per_page, total_pages, has_next, has_prev)
    """
    start = perf_counter()
    logger.info(
        "tasks.list.start project_id=%s sprint_id=%s status=%s assignee=%s skip=%s limit=%s",
        project_id,
        sprint_id,
        status,
        assignee,
        skip,
        limit,
    )

    # Use caching for common queries
    from app.services.cache_service import cache_service

    cache_key = cache_service._make_key(
        "tasks_list_paginated",
        project_id=project_id,
        sprint_id=sprint_id,
        status=status,
        assignee=assignee,
        skip=skip,
        limit=limit,
    )
    cached_result = cache_service.get(cache_key)
    if cached_result:
        logger.info("tasks.list.cache_hit duration=%.3f", perf_counter() - start)
        return cached_result

    try:
        # Build filter conditions
        filters = []
        if sprint_id:
            filters.append(Task.sprint_id == sprint_id)
        if project_id:
            filters.append(Task.project_id == project_id)
        if assignee:
            filters.append(Task.assignee_email == assignee)
        if status:
            filters.append(Task.status == status)

        # Count query (runs in parallel with data query)
        count_query = select(func.count(Task.id))
        if filters:
            count_query = count_query.where(and_(*filters))

        # Data query
        data_query = select(Task)
        if filters:
            data_query = data_query.where(and_(*filters))
        data_query = data_query.order_by(Task.id).offset(skip).limit(limit)

        try:
            # AsyncSession does not support overlapping operations on the same connection.
            count_result = await asyncio.wait_for(db.execute(count_query), timeout=30.0)
            data_result = await asyncio.wait_for(db.execute(data_query), timeout=30.0)

            total = count_result.scalar() or 0
            tasks = list(data_result.scalars().all())

            # Build paginated response
            result = paginated_response(
                data=[TaskSchema.model_validate(t).model_dump() for t in tasks],
                total=total,
                skip=skip,
                limit=limit,
            )

            # Cache the result for smaller queries
            if limit <= 100:
                cache_service.set(cache_key, result, ttl=60)
            elif limit <= 500:
                cache_service.set(cache_key, result, ttl=30)

            logger.info(
                "tasks.list.success count=%s total=%s duration=%.3f",
                len(tasks),
                total,
                perf_counter() - start,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                "tasks.list.timeout project_id=%s sprint_id=%s limit=%s duration=%.3f",
                project_id,
                sprint_id,
                limit,
                perf_counter() - start,
            )
            raise HTTPException(status_code=504, detail="Query timeout - try with smaller limit")

    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "tasks.list.error project_id=%s sprint_id=%s status=%s assignee=%s duration=%.3f",
            project_id,
            sprint_id,
            status,
            assignee,
            perf_counter() - start,
        )
        raise


@router.get("/{task_id}", response_model=TaskWithRelations)
async def get_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_VIEW)),
):
    """Get task with relations"""
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    # Calculate additional fields (explicit mapping to avoid leaking SA internals)
    task_dict = {c.name: getattr(task, c.name) for c in task.__table__.columns}

    # Guard division by zero and missing values
    if (task.estimate_hours or 0) > 0 and (task.spent_hours or 0) >= 0:
        task_dict["deviation_hours"] = (task.spent_hours or 0) - (task.estimate_hours or 0)
        task_dict["completion_rate"] = (task.spent_hours or 0) / (task.estimate_hours or 1) * 100

    project = task.project
    if project is not None:
        task_dict["project_name"] = project.name

    sprint = task.sprint
    if sprint is not None:
        task_dict["sprint_name"] = sprint.name

    return task_dict


@router.post("/", response_model=TaskSchema)
async def create_task(
    task: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_CREATE)),
):
    """Create new task"""
    # Use transaction with optional FOR UPDATE to prevent races on unique jira_id
    try:
        async with db.begin():
            sel = select(Task).where(Task.jira_id == task.jira_id)
            result = await execute_with_lock(db, sel)
            if result.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Task with this Jira ID already exists")
            db_task = Task(**task.dict())
            db.add(db_task)
        await db.refresh(db_task)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Task with this Jira ID already exists")

    # Invalidate caches affected by task creation
    await CacheInvalidator.on_task_update(db_task.project_id, db_task.sprint_id)

    return db_task


@router.patch("/{task_id}", response_model=TaskSchema)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_UPDATE)),
):
    """Update task"""
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    update_data = task_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(task, field, value)

    try:
        async with db.begin():
            for field, value in update_data.items():
                setattr(task, field, value)
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(task)

    # Invalidate caches affected by task update
    await CacheInvalidator.on_task_update(task.project_id, task.sprint_id)

    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_DELETE)),
):
    """Delete task"""
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    # Store project/sprint IDs before deletion
    project_id = task.project_id
    sprint_id = task.sprint_id

    async with transactional_session(db):
        await db.delete(task)

    # Invalidate caches affected by task deletion
    await CacheInvalidator.on_task_update(project_id, sprint_id)

    return {"message": "Task deleted successfully"}


@router.post("/export", status_code=202)
async def export_tasks_async(
    project_id: Optional[int] = Query(None),
    sprint_id: Optional[int] = Query(None),
):
    """Start an asynchronous task export and return a polling task ID."""
    task_id = task_manager.create_task("tasks_export")
    asyncio.create_task(_run_task_export_job(task_id, project_id, sprint_id))
    return {
        "status": "pending",
        "task_id": task_id,
        "download_url": f"/api/v1/tasks/exports/{task_id}/download",
    }


@router.get("/exports/{task_id}/download")
async def download_exported_tasks(task_id: str):
    """Download a completed asynchronous task export."""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status.value != "completed":
        raise HTTPException(status_code=409, detail="Task export is not completed yet")

    export_path = _task_export_path(task_id)
    if not export_path.exists():
        raise HTTPException(status_code=404, detail="Export file not found")

    return FileResponse(
        export_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=export_path.name,
    )


@router.post("/export/excel")
async def export_tasks_to_excel(
    project_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Export tasks to Excel"""
    query = select(Task).order_by(Task.id)
    if project_id:
        query = query.where(Task.project_id == project_id)
    if sprint_id:
        query = query.where(Task.sprint_id == sprint_id)

    result = await db.execute(query)
    tasks = list(result.scalars().all())
    output = _render_tasks_excel(_task_export_rows(tasks))

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tasks_export.xlsx"},
    )


@router.post("/{task_id}/business-value")
async def set_task_business_value(
    task_id: int,
    business_value: Optional[float] = Query(None, ge=0.0, description="Business value (>= 0)"),
    value_delivered: Optional[bool] = Query(None, description="Whether value has been delivered"),
    reason: Optional[str] = Query(None, description="Optional reason/comment"),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Update business value/value_delivered and recompute ROI when possible.

    Returns the updated task snapshot and a minimal change audit for transparency.
    """
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    old_value = task.business_value
    old_delivered = task.value_delivered
    old_roi = task.roi

    changed = False
    if business_value is not None:
        try:
            task.business_value = float(business_value)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid business_value")
        changed = True
    if value_delivered is not None:
        task.value_delivered = bool(value_delivered)
        changed = True

    # Recompute ROI if we have data
    try:
        business_value_val = task.business_value
        spent_hours_val = task.spent_hours
        if (task.value_delivered or False) and business_value_val is not None:
            if spent_hours_val is not None and spent_hours_val != 0:
                task.roi = float(business_value_val) / float(spent_hours_val)
        elif task.spent_hours in (None, 0):
            if task.value_delivered and task.business_value is not None:
                task.roi = 0.0
    except Exception:
        task.roi = old_roi

    if changed:
        # Write audit row (changed_by unknown here; auth is optional)
        async with transactional_session(db):
            try:
                audit = BusinessValueAudit(
                    task_id=task.id,
                    old_value=old_value,
                    new_value=task.business_value,
                    old_delivered=old_delivered,
                    new_delivered=task.value_delivered,
                    old_roi=old_roi,
                    new_roi=task.roi,
                    changed_by=None,
                    reason=reason,
                )
                db.add(audit)
            except Exception:
                pass
        await db.refresh(task)

        # Invalidate caches affected by business value update
        await CacheInvalidator.on_task_update(task.project_id, task.sprint_id)

    try:
        logger.info(
            "Task %s business value update: value %s->%s, delivered %s->%s, roi %s->%s",
            task_id,
            old_value,
            task.business_value,
            old_delivered,
            task.value_delivered,
            old_roi,
            task.roi,
        )
    except Exception:
        pass

    return {
        "task": TaskSchema.from_orm(task).dict(),
        "changes": {
            "business_value": {"old": old_value, "new": task.business_value},
            "value_delivered": {"old": old_delivered, "new": task.value_delivered},
            "roi": {"old": old_roi, "new": task.roi},
        },
    }


@router.get("/{task_id}/business-value/audit")
async def get_task_business_value_audit(
    task_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Return recent business value audit records for a task."""
    with handle_api_error(operation="get_task_business_value_audit", context={"task_id": task_id}):
        from sqlalchemy import desc

        res = await db.execute(
            select(BusinessValueAudit)
            .where(BusinessValueAudit.task_id == task_id)
            .order_by(desc(BusinessValueAudit.created_at))
            .limit(limit)
        )
        rows = res.scalars().all()
        out = []
        for r in rows:
            out.append(
                {
                    "id": r.id,
                    "task_id": r.task_id,
                    "old_value": r.old_value,
                    "new_value": r.new_value,
                    "old_delivered": r.old_delivered,
                    "new_delivered": r.new_delivered,
                    "old_roi": r.old_roi,
                    "new_roi": r.new_roi,
                    "changed_by": r.changed_by,
                    "reason": r.reason,
                    "created_at": r.created_at,
                }
            )
        return {"total": len(out), "audit": out}


# =============================================================================
# Batch Operations (Performance Optimization)
# =============================================================================


@router.delete("/batch")
async def batch_delete_tasks(
    task_ids: List[int] = Body(
        ..., description="List of task IDs to delete", min_length=1, max_length=500
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_DELETE)),
) -> Dict[str, Any]:
    """
    Delete multiple tasks in a single optimized operation.

    Uses bulk DELETE query instead of N individual queries.
    Maximum 500 tasks per request.

    Returns:
        deleted: number of tasks deleted
        requested: number of task IDs provided
    """
    start = perf_counter()
    logger.info("tasks.batch_delete.start count=%s user=%s", len(task_ids), current_user.id)

    if not task_ids:
        raise HTTPException(status_code=400, detail="No task IDs provided")

    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 tasks per batch delete")

    async with async_handle_api_error(
        operation="batch_delete_tasks",
        context={"count": len(task_ids), "user_id": current_user.id},
        db_session=db,
    ):
        deleted_count = await bulk_delete_by_ids(db, Task, task_ids, chunk_size=100)

        # Invalidate related caches
        from app.services.cache_service import cache_service

        if hasattr(cache_service, "invalidate_pattern"):
            cache_service.invalidate_pattern("tasks_list*")

        logger.info(
            "tasks.batch_delete.success deleted=%s requested=%s duration=%.3f",
            deleted_count,
            len(task_ids),
            perf_counter() - start,
        )

        return {"deleted": deleted_count, "requested": len(task_ids), "success": True}


@router.patch("/batch")
async def batch_update_tasks(
    task_ids: List[int] = Body(
        ..., description="List of task IDs to update", min_length=1, max_length=500
    ),
    updates: Dict[str, Any] = Body(..., description="Fields to update"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_UPDATE)),
) -> Dict[str, Any]:
    """
    Update multiple tasks with the same values in a single optimized operation.

    Uses bulk UPDATE query instead of N individual queries.
    Maximum 500 tasks per request.

    Allowed update fields:
        - status: Task status
        - priority: Task priority
        - assignee_email: Assignee email
        - assignee_name: Assignee display name

    Returns:
        updated: number of tasks updated
        requested: number of task IDs provided
    """
    start = perf_counter()
    logger.info("tasks.batch_update.start count=%s user=%s", len(task_ids), current_user.id)

    if not task_ids:
        raise HTTPException(status_code=400, detail="No task IDs provided")

    if len(task_ids) > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 tasks per batch update")

    if not updates:
        raise HTTPException(status_code=400, detail="No update fields provided")

    # Whitelist allowed fields for bulk update (prevent arbitrary updates)
    allowed_fields = {"status", "priority", "assignee_email", "assignee_name"}
    filtered_updates = {k: v for k, v in updates.items() if k in allowed_fields}

    if not filtered_updates:
        raise HTTPException(
            status_code=400, detail=f"No valid update fields. Allowed: {', '.join(allowed_fields)}"
        )

    async with async_handle_api_error(
        operation="batch_update_tasks",
        context={
            "count": len(task_ids),
            "fields": list(filtered_updates.keys()),
            "user_id": current_user.id,
        },
        db_session=db,
    ):
        updated_count = await bulk_update_by_ids(
            db, Task, task_ids, filtered_updates, chunk_size=100
        )

        # Invalidate related caches
        from app.services.cache_service import cache_service

        if hasattr(cache_service, "invalidate_pattern"):
            cache_service.invalidate_pattern("tasks_list*")

        logger.info(
            "tasks.batch_update.success updated=%s requested=%s fields=%s duration=%.3f",
            updated_count,
            len(task_ids),
            list(filtered_updates.keys()),
            perf_counter() - start,
        )

        return {
            "updated": updated_count,
            "requested": len(task_ids),
            "fields": list(filtered_updates.keys()),
            "success": True,
        }
