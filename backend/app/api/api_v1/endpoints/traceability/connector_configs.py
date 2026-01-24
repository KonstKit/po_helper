from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user, ensure_project_access
from app.models import User
from app.models.traceability import ConnectorConfig as ConnectorConfigModel
from app.schemas.traceability import ConnectorConfig, ConnectorConfigBase
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


@router.get("/connector-configs", response_model=List[ConnectorConfig])
async def list_connector_configs(
    project_id: Optional[int] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(ConnectorConfigModel).order_by(ConnectorConfigModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(ConnectorConfigModel.project_id == project_id)
    if provider:
        stmt = stmt.where(ConnectorConfigModel.provider == provider)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/connector-configs", response_model=ConnectorConfig)
async def create_connector_config(
    payload: ConnectorConfigBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await ensure_project_access(payload.project_id, db, current_user)
    connector = ConnectorConfigModel(**payload.model_dump())
    async with transactional_session(db):
        db.add(connector)
    await db.refresh(connector)
    return connector


@router.get("/connector-configs/{config_id}", response_model=ConnectorConfig)
async def get_connector_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await get_by_id_or_404(db, ConnectorConfigModel, config_id)
    if connector.project_id is not None:
        await ensure_project_access(connector.project_id, db, current_user)
    return connector


@router.delete("/connector-configs/{config_id}")
async def delete_connector_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    connector = await get_by_id_or_404(db, ConnectorConfigModel, config_id)
    if connector.project_id is not None:
        await ensure_project_access(connector.project_id, db, current_user)
    async with transactional_session(db):
        await db.delete(connector)
    return {"status": "deleted", "id": config_id}
