from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import ConnectorConfig


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
    return ConnectorOverrides(
        provider=row.provider,
        enabled=bool(row.is_enabled),
        settings=row.settings_json or {},
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
        overrides[row.provider] = ConnectorOverrides(
            provider=row.provider,
            enabled=bool(row.is_enabled),
            settings=row.settings_json or {},
            connector_id=row.id,
        )
    return overrides
