from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_project_access, require_permission
from app.core.database import get_db
from app.models import Permissions, User
from app.models.traceability import AuditLog as AuditLogModel
from app.schemas.traceability import AuditLog

router = APIRouter()


@router.get("/audit-logs", response_model=List[AuditLog])
async def list_audit_logs(
    project_id: Optional[int] = Query(default=None),
    actor_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None),
    entity_type: Optional[str] = Query(default=None),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    stmt = select(AuditLogModel).order_by(AuditLogModel.created_at.desc())

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(AuditLogModel.project_id == project_id)
    elif not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")

    if actor_id is not None:
        stmt = stmt.where(AuditLogModel.actor_id == actor_id)
    if action:
        stmt = stmt.where(AuditLogModel.action == action)
    if entity_type:
        stmt = stmt.where(AuditLogModel.entity_type == entity_type)
    if start_time:
        stmt = stmt.where(AuditLogModel.created_at >= start_time)
    if end_time:
        stmt = stmt.where(AuditLogModel.created_at <= end_time)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
