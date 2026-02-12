from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.request_context import get_actor_id, get_request_id
from app.models.traceability import AuditLog


async def record_audit_event(
    db: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: int,
    actor_id: Optional[int] = None,
    project_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    outcome: str = "success",
    payload: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> AuditLog:
    """Persist an audit log entry with request context."""
    resolved_actor_id = actor_id if actor_id is not None else get_actor_id()
    resolved_request_id = request_id if request_id is not None else get_request_id()

    audit = AuditLog(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=resolved_actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=resolved_request_id,
        outcome=outcome,
        payload=payload or {},
    )
    db.add(audit)
    await db.flush()
    return audit


def record_audit_event_sync(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int,
    actor_id: Optional[int] = None,
    project_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    outcome: str = "success",
    payload: Optional[dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> AuditLog:
    """Persist an audit log entry with request context (sync session)."""
    resolved_actor_id = actor_id if actor_id is not None else get_actor_id()
    resolved_request_id = request_id if request_id is not None else get_request_id()

    audit = AuditLog(
        tenant_id=tenant_id,
        project_id=project_id,
        actor_id=resolved_actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=resolved_request_id,
        outcome=outcome,
        payload=payload or {},
    )
    db.add(audit)
    db.flush()
    return audit
