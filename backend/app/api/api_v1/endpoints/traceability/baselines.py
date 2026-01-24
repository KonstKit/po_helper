from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user, ensure_project_access
from app.models import User
from app.models.traceability import Baseline as BaselineModel
from app.models.traceability import BaselineItem as BaselineItemModel
from app.schemas.traceability import Baseline, BaselineBase, BaselineItem, BaselineItemBase
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


@router.get("/baselines", response_model=List[Baseline])
async def list_baselines(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(BaselineModel).order_by(BaselineModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(BaselineModel.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/baselines", response_model=Baseline)
async def create_baseline(
    payload: BaselineBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await ensure_project_access(payload.project_id, db, current_user)
    baseline = BaselineModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(baseline)
    await db.refresh(baseline)
    return baseline


@router.get("/baselines/{baseline_id}", response_model=Baseline)
async def get_baseline(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    return baseline


@router.delete("/baselines/{baseline_id}")
async def delete_baseline(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    async with transactional_session(db):
        await db.delete(baseline)
    return {"status": "deleted", "id": baseline_id}


@router.get("/baselines/{baseline_id}/items", response_model=List[BaselineItem])
async def list_baseline_items(
    baseline_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    result = await db.execute(
        select(BaselineItemModel).where(BaselineItemModel.baseline_id == baseline_id)
    )
    return list(result.scalars().all())


@router.post("/baselines/{baseline_id}/items", response_model=BaselineItem)
async def add_baseline_item(
    baseline_id: int,
    payload: BaselineItemBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    if payload.baseline_id != baseline_id:
        raise HTTPException(status_code=400, detail="baseline_id mismatch")
    if payload.artifact_id is None and payload.link_id is None:
        raise HTTPException(status_code=400, detail="artifact_id or link_id is required")
    item = BaselineItemModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(item)
    await db.refresh(item)
    return item


@router.delete("/baselines/{baseline_id}/items/{item_id}")
async def delete_baseline_item(
    baseline_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    baseline = await get_by_id_or_404(db, BaselineModel, baseline_id)
    if baseline.project_id is not None:
        await ensure_project_access(baseline.project_id, db, current_user)
    item = await get_by_id_or_404(db, BaselineItemModel, item_id)
    if item.baseline_id != baseline_id:
        raise HTTPException(status_code=400, detail="baseline_id mismatch")
    async with transactional_session(db):
        await db.delete(item)
    return {"status": "deleted", "id": item_id}
