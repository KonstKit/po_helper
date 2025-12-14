from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from time import perf_counter
from app.core.database import get_db
from app.models import Task, BusinessValueAudit, User, Permissions
from app.schemas.task import Task as TaskSchema, TaskCreate, TaskUpdate, TaskWithRelations
from app.api.deps import require_permission
from app.utils import transactional_session, handle_api_error, paginate_query, get_or_404, execute_with_lock
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/", response_model=List[TaskSchema])
async def get_tasks(
    project_id: Optional[int] = Query(None),
    sprint_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = Query(100, le=1000),  # Max limit of 1000 to prevent excessive loads
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_VIEW))
):
    """Get tasks with filters - optimized for performance with large datasets"""
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
        "tasks_list",
        project_id=project_id,
        sprint_id=sprint_id,
        status=status,
        assignee=assignee,
        skip=skip,
        limit=limit
    )
    cached_result = cache_service.get(cache_key)
    if cached_result:
        logger.info("tasks.list.cache_hit duration=%.3f", perf_counter() - start)
        return cached_result

    try:
        # Build optimized query with only necessary columns for listing
        # Use joinedload for related data if needed
        query = select(Task)

        # Apply filters in order of selectivity (most selective first)
        if sprint_id:  # Most selective typically
            query = query.where(Task.sprint_id == sprint_id)
        if project_id:
            query = query.where(Task.project_id == project_id)
        if assignee:
            query = query.where(Task.assignee_email == assignee)
        if status:
            query = query.where(Task.status == status)

        # Add ordering for consistent pagination
        query = query.order_by(Task.id)

        # Execute with timeout protection
        import asyncio
        try:
            tasks = await asyncio.wait_for(
                paginate_query(db, query, skip, limit),
                timeout=30.0  # 30 second timeout for large queries
            )

            # Cache the result for smaller queries
            if limit <= 100:
                cache_service.set(cache_key, tasks, ttl=60)  # Cache for 1 minute
            elif limit <= 500:
                cache_service.set(cache_key, tasks, ttl=30)  # Cache for 30 seconds for medium queries
            # Don't cache very large queries (>500)

            logger.info(
                "tasks.list.success count=%s duration=%.3f",
                len(tasks),
                perf_counter() - start,
            )
            return tasks

        except asyncio.TimeoutError:
            logger.error(
                "tasks.list.timeout project_id=%s sprint_id=%s limit=%s duration=%.3f",
                project_id,
                sprint_id,
                limit,
                perf_counter() - start,
            )
            # Inform client explicitly about timeout
            raise HTTPException(status_code=504, detail="Query timeout - try with smaller limit")

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
    current_user: User = Depends(require_permission(Permissions.TASK_VIEW))
):
    """Get task with relations"""
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    # Calculate additional fields (explicit mapping to avoid leaking SA internals)
    task_dict = {c.name: getattr(task, c.name) for c in task.__table__.columns}

    # Guard division by zero and missing values
    if (task.estimate_hours or 0) > 0 and (task.spent_hours or 0) >= 0:
        task_dict["deviation_hours"] = (task.spent_hours or 0) - (task.estimate_hours or 0)
        task_dict["completion_rate"] = ((task.spent_hours or 0) / (task.estimate_hours or 1) * 100)

    if getattr(task, "project", None):
        try:
            task_dict["project_name"] = task.project.name
        except Exception:
            pass

    if getattr(task, "sprint", None):
        try:
            task_dict["sprint_name"] = task.sprint.name
        except Exception:
            pass

    return task_dict


@router.post("/", response_model=TaskSchema)
async def create_task(
    task: TaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_CREATE))
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
    
    return db_task


@router.patch("/{task_id}", response_model=TaskSchema)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_UPDATE))
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
    
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TASK_DELETE))
):
    """Delete task"""
    task = await get_or_404(db, select(Task).where(Task.id == task_id), "Task")

    async with transactional_session(db):
        await db.delete(task)

    return {"message": "Task deleted successfully"}


@router.post("/export/excel")
async def export_tasks_to_excel(
    project_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """Export tasks to Excel"""
    import pandas as pd
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    
    # Get tasks
    query = select(Task)
    if project_id:
        query = query.where(Task.project_id == project_id)
    if sprint_id:
        query = query.where(Task.sprint_id == sprint_id)
    
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    # Convert to DataFrame
    data = []
    for task in tasks:
        data.append({
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
            "Due Date": task.due_date
        })
    
    df = pd.DataFrame(data)
    
    # Create Excel file
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Tasks', index=False)
        
        # Get workbook and worksheet
        workbook = writer.book
        worksheet = writer.sheets['Tasks']
        
        # Add formatting
        header_format = workbook.add_format({
            'bold': True,
            'bg_color': '#4472C4',
            'font_color': 'white',
            'border': 1
        })
        
        # Write headers with formatting
        for col_num, value in enumerate(df.columns.values):
            worksheet.write(0, col_num, value, header_format)
        
        # Auto-adjust column widths
        for i, col in enumerate(df.columns):
            column_width = max(df[col].astype(str).map(len).max(), len(col)) + 2
            worksheet.set_column(i, i, min(column_width, 50))
    
    output.seek(0)
    
    return StreamingResponse(
        output,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={"Content-Disposition": "attachment; filename=tasks_export.xlsx"}
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
        if (task.value_delivered or False) and task.business_value is not None and task.spent_hours not in (None, 0):
            task.roi = float(task.business_value) / float(task.spent_hours)
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

    try:
        logger.info(
            "Task %s business value update: value %s->%s, delivered %s->%s, roi %s->%s",
            task_id, old_value, task.business_value, old_delivered, task.value_delivered, old_roi, task.roi,
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
            select(BusinessValueAudit).where(BusinessValueAudit.task_id == task_id).order_by(desc(BusinessValueAudit.created_at)).limit(limit)
        )
        rows = res.scalars().all()
        out = []
        for r in rows:
            out.append({
                'id': r.id,
                'task_id': r.task_id,
                'old_value': r.old_value,
                'new_value': r.new_value,
                'old_delivered': r.old_delivered,
                'new_delivered': r.new_delivered,
                'old_roi': r.old_roi,
                'new_roi': r.new_roi,
                'changed_by': r.changed_by,
                'reason': r.reason,
                'created_at': r.created_at,
            })
        return { 'total': len(out), 'audit': out }
