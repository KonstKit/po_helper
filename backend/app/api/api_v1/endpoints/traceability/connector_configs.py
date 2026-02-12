from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings
from app.api.deps import ensure_project_access, require_permission
from app.core.rate_limit import limiter
from app.models import User, Permissions
from app.models.traceability import ConnectorConfig as ConnectorConfigModel
from app.schemas.traceability import ConnectorConfig, ConnectorConfigBase
from app.services.connector_secrets import (
    encrypt_connector_settings,
    redact_connector_settings,
    settings_have_secrets,
)
from app.services.audit_log import record_audit_event
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


def _require_dedicated_encryption_key() -> None:
    if not settings.ENCRYPTION_SECRET or settings.ENCRYPTION_SECRET == settings.SECRET_KEY:
        raise HTTPException(
            status_code=500,
            detail="ENCRYPTION_SECRET must be set and differ from SECRET_KEY",
        )


def _to_connector_schema(connector: ConnectorConfigModel) -> ConnectorConfig:
    return ConnectorConfig(
        id=connector.id,
        project_id=connector.project_id,
        provider=connector.provider,
        is_enabled=connector.is_enabled,
        settings_json=redact_connector_settings(connector.settings_json),
        auth_ref=connector.auth_ref,
        rate_limit_policy=connector.rate_limit_policy,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


@router.get("/connector-configs", response_model=List[ConnectorConfig])
async def list_connector_configs(
    project_id: Optional[int] = Query(default=None),
    provider: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    stmt = select(ConnectorConfigModel).order_by(ConnectorConfigModel.created_at.desc())
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(ConnectorConfigModel.project_id == project_id)
    elif not current_user.has_permission(Permissions.ADMIN):
        raise HTTPException(status_code=403, detail="project_id is required")
    if provider:
        stmt = stmt.where(ConnectorConfigModel.provider == provider)
    result = await db.execute(stmt)
    return [_to_connector_schema(row) for row in result.scalars().all()]


@router.post("/connector-configs", response_model=ConnectorConfig)
@limiter.limit("10/minute")
async def create_connector_config(
    request: Request,
    payload: ConnectorConfigBase,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.INTEGRATION_MANAGE)),
):
    if payload.project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required")
    await ensure_project_access(payload.project_id, db, current_user)
    payload_data = payload.model_dump()
    settings_json = payload_data.get("settings_json") or {}
    if settings_have_secrets(settings_json):
        _require_dedicated_encryption_key()
        payload_data["settings_json"] = encrypt_connector_settings(settings_json)
    connector = ConnectorConfigModel(**payload_data)
    async with transactional_session(db):
        db.add(connector)
        await db.flush()
        await record_audit_event(
            db,
            action="create",
            entity_type="connector_config",
            entity_id=connector.id,
            actor_id=current_user.id,
            project_id=connector.project_id,
            payload={
                "provider": connector.provider,
                "is_enabled": connector.is_enabled,
                "rate_limit_policy": connector.rate_limit_policy,
            },
        )
    await db.refresh(connector)
    return _to_connector_schema(connector)


@router.get("/connector-configs/{config_id}", response_model=ConnectorConfig)
async def get_connector_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    connector = await get_by_id_or_404(db, ConnectorConfigModel, config_id)
    if connector.project_id is not None:
        await ensure_project_access(connector.project_id, db, current_user)
    return _to_connector_schema(connector)


@router.delete("/connector-configs/{config_id}")
@limiter.limit("10/minute")
async def delete_connector_config(
    request: Request,
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.INTEGRATION_MANAGE)),
):
    connector = await get_by_id_or_404(db, ConnectorConfigModel, config_id)
    if connector.project_id is not None:
        await ensure_project_access(connector.project_id, db, current_user)
    async with transactional_session(db):
        await record_audit_event(
            db,
            action="delete",
            entity_type="connector_config",
            entity_id=connector.id,
            actor_id=current_user.id,
            project_id=connector.project_id,
            payload={"provider": connector.provider},
        )
        await db.delete(connector)
    return {"status": "deleted", "id": config_id}
