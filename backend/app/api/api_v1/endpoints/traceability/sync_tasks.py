from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import ensure_project_access, require_permission
from app.models import User, Permissions
from app.models.traceability import SyncTask as SyncTaskModel
from app.schemas.traceability import SyncTask
from app.services.sync_tracking import recover_stale_running_sync_tasks
from app.utils import get_by_id_or_404

router = APIRouter()


@router.get("/sync-tasks", response_model=List[SyncTask])
async def list_sync_tasks(
    project_id: Optional[int] = Query(default=None),
    source_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    recovered = await recover_stale_running_sync_tasks(db)
    if recovered:
        await db.commit()

    stmt = select(SyncTaskModel).order_by(SyncTaskModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(SyncTaskModel.project_id == project_id)
    elif not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if source_id is not None:
        stmt = stmt.where(SyncTaskModel.source_id == source_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/sync-tasks/{task_id}", response_model=SyncTask)
async def get_sync_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    recovered = await recover_stale_running_sync_tasks(db)
    if recovered:
        await db.commit()

    task = await get_by_id_or_404(db, SyncTaskModel, task_id)
    if task.project_id is not None:
        await ensure_project_access(task.project_id, db, current_user)
    return task
