from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import ensure_project_access, require_permission
from app.models import User, Permissions
from app.models.traceability import Projection as ProjectionModel
from app.models.traceability import ProjectionItem as ProjectionItemModel
from app.schemas.traceability import (
    Projection,
    ProjectionBase,
    ProjectionItem,
    ProjectionItemBase,
)
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


@router.get("/projections", response_model=List[Projection])
async def list_projections(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    stmt = select(ProjectionModel).order_by(ProjectionModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(ProjectionModel.project_id == project_id)
    elif not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/projections", response_model=Projection)
async def create_projection(
    payload: ProjectionBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    if payload.project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await ensure_project_access(payload.project_id, db, current_user)
    projection = ProjectionModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(projection)
    await db.refresh(projection)
    return projection


@router.get("/projections/{projection_id}", response_model=Projection)
async def get_projection(
    projection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    projection = await get_by_id_or_404(db, ProjectionModel, projection_id)
    if projection.project_id is not None:
        await ensure_project_access(projection.project_id, db, current_user)
    return projection


@router.delete("/projections/{projection_id}")
async def delete_projection(
    projection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    projection = await get_by_id_or_404(db, ProjectionModel, projection_id)
    if projection.project_id is not None:
        await ensure_project_access(projection.project_id, db, current_user)
    async with transactional_session(db):
        await db.delete(projection)
    return {"status": "deleted", "id": projection_id}


@router.get("/projections/{projection_id}/items", response_model=List[ProjectionItem])
async def list_projection_items(
    projection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    projection = await get_by_id_or_404(db, ProjectionModel, projection_id)
    if projection.project_id is not None:
        await ensure_project_access(projection.project_id, db, current_user)
    result = await db.execute(
        select(ProjectionItemModel).where(ProjectionItemModel.projection_id == projection_id)
    )
    return list(result.scalars().all())


@router.post("/projections/{projection_id}/items", response_model=ProjectionItem)
async def add_projection_item(
    projection_id: int,
    payload: ProjectionItemBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    projection = await get_by_id_or_404(db, ProjectionModel, projection_id)
    if projection.project_id is not None:
        await ensure_project_access(projection.project_id, db, current_user)
    if payload.projection_id != projection_id:
        raise HTTPException(status_code=400, detail="projection_id mismatch")
    if payload.artifact_id is None and payload.link_id is None:
        raise HTTPException(status_code=400, detail="artifact_id or link_id is required")
    item = ProjectionItemModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(item)
    await db.refresh(item)
    return item


@router.delete("/projections/{projection_id}/items/{item_id}")
async def delete_projection_item(
    projection_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    projection = await get_by_id_or_404(db, ProjectionModel, projection_id)
    if projection.project_id is not None:
        await ensure_project_access(projection.project_id, db, current_user)
    item = await get_by_id_or_404(db, ProjectionItemModel, item_id)
    if item.projection_id != projection_id:
        raise HTTPException(status_code=400, detail="projection_id mismatch")
    async with transactional_session(db):
        await db.delete(item)
    return {"status": "deleted", "id": item_id}
