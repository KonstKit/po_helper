from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import ConnectorConfig
from app.services.connector_secrets import (
    decrypt_connector_settings,
    encrypt_connector_settings,
    has_dedicated_encryption_secret,
)


@dataclass(frozen=True)
class ConnectorOverrides:
    provider: str
    enabled: bool
    settings: Dict[str, Any]
    connector_id: Optional[int]


async def get_connector_overrides(
    db: AsyncSession, project_id: Optional[int], provider: str
) -> Optional[ConnectorOverrides]:
    if project_id is None:
        return None
    stmt = (
        select(ConnectorConfig)
        .where(ConnectorConfig.project_id == project_id, ConnectorConfig.provider == provider)
        .order_by(ConnectorConfig.created_at.desc())
    )
    row = (await db.execute(stmt)).scalars().first()
    if row is None:
        return None
    settings, needs_reencrypt = decrypt_connector_settings(row.settings_json or {})
    if needs_reencrypt and has_dedicated_encryption_secret():
        row.settings_json = encrypt_connector_settings(settings)
        await db.flush()
        await db.commit()
    return ConnectorOverrides(
        provider=row.provider,
        enabled=bool(row.is_enabled),
        settings=settings,
        connector_id=row.id,
    )


async def get_connector_overrides_map(
    db: AsyncSession, project_id: Optional[int], providers: Iterable[str]
) -> Dict[str, ConnectorOverrides]:
    if project_id is None:
        return {}
    provider_list = [p for p in providers if p]
    if not provider_list:
        return {}
    stmt = (
        select(ConnectorConfig)
        .where(
            ConnectorConfig.project_id == project_id,
            ConnectorConfig.provider.in_(provider_list),
        )
        .order_by(ConnectorConfig.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    overrides: Dict[str, ConnectorOverrides] = {}
    for row in rows:
        if row.provider in overrides:
            continue
        settings, needs_reencrypt = decrypt_connector_settings(row.settings_json or {})
        if needs_reencrypt and has_dedicated_encryption_secret():
            row.settings_json = encrypt_connector_settings(settings)
            await db.flush()
            await db.commit()
        overrides[row.provider] = ConnectorOverrides(
            provider=row.provider,
            enabled=bool(row.is_enabled),
            settings=settings,
            connector_id=row.id,
        )
    return overrides
