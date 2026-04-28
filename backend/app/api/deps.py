from __future__ import annotations

import ipaddress
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.database import get_db
from app.core.request_context import (
    get_token_scopes,
    get_token_tenant_id,
    set_actor_id,
    set_token_scopes,
    set_token_tenant_id,
)
from app.core.security import decode_token, get_password_hash
from app.models.rbac import Permissions
from app.models import Project, Role, User
from app.utils import handle_api_error

logger = logging.getLogger(__name__)


def _clear_auth_context() -> None:
    set_token_scopes(None)
    set_token_tenant_id(None)
    set_actor_id(None)


def _is_loopback_host(host: str | None) -> bool:
    normalized = (host or "").strip().strip("[]").lower()
    if not normalized:
        return False
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _extract_host_without_port(host: str | None) -> str | None:
    normalized = (host or "").strip()
    if not normalized:
        return None
    if normalized.startswith("["):
        closing = normalized.find("]")
        if closing != -1:
            return normalized[1:closing]
        return normalized[1:]
    if normalized.count(":") == 1:
        return normalized.split(":", 1)[0]
    return normalized


def _is_local_origin(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_loopback_host(parsed.hostname)


def _is_local_demo_request(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    if not _is_loopback_host(client_host):
        return False

    host_header = request.headers.get("host")
    request_host = request.url.hostname
    if not _is_loopback_host(_extract_host_without_port(host_header) or request_host):
        return False

    return _is_local_origin(request.headers.get("origin"))


def _normalize_token_scopes(scopes: Any) -> Optional[tuple[str, ...]]:
    if scopes is None:
        return None
    if isinstance(scopes, str):
        return (scopes,)

    try:
        normalized = tuple(
            dict.fromkeys(
                scope.strip()
                for scope in scopes
                if isinstance(scope, str) and scope.strip()
            )
        )
    except TypeError:
        return None

    return normalized


def _normalize_tenant_id(tenant_id: Any) -> Optional[str]:
    if tenant_id is None:
        return None
    normalized = str(tenant_id).strip()
    return normalized or None


def _project_meta(project: Project) -> dict[str, Any]:
    meta = project.meta
    if isinstance(meta, dict):
        return meta
    return {}


def _project_tenant_id(project: Project) -> Optional[str]:
    return _normalize_tenant_id(_project_meta(project).get("tenant_id"))


def _project_member_ids(project: Project) -> set[int]:
    member_ids: set[int] = set()
    raw_member_ids = _project_meta(project).get("member_ids")
    if not isinstance(raw_member_ids, list):
        return member_ids

    for member_id in raw_member_ids:
        if isinstance(member_id, bool):
            continue
        try:
            member_ids.add(int(member_id))
        except (TypeError, ValueError):
            continue
    return member_ids


def _is_admin_access(current_user: User) -> bool:
    token_scopes = get_token_scopes()
    if token_scopes is not None:
        return Permissions.ADMIN in token_scopes
    return bool(current_user.is_superuser or current_user.has_permission(Permissions.ADMIN))


def has_admin_access(current_user: User) -> bool:
    """Public helper for scope-aware admin checks."""
    return _is_admin_access(current_user)


def can_access_project(project: Project, current_user: User) -> bool:
    """In-memory project access check aligned with ensure_project_access."""
    if not current_user.is_active:
        return False

    if _is_admin_access(current_user):
        token_tenant_id = get_token_tenant_id()
        project_tenant_id = _project_tenant_id(project)
        if token_tenant_id is not None:
            if project_tenant_id is None:
                return False
            return str(token_tenant_id) == str(project_tenant_id)
        return True

    token_tenant_id = get_token_tenant_id()
    project_tenant_id = _project_tenant_id(project)

    # Enforce strict tenant consistency when either side carries tenant context.
    if project_tenant_id is not None or token_tenant_id is not None:
        if token_tenant_id is None or project_tenant_id is None:
            return False
        if str(token_tenant_id) != str(project_tenant_id):
            return False

    if project.owner_id == current_user.id:
        return True

    if current_user.id in _project_member_ids(project):
        return True

    return False


async def _get_or_create_demo_user(db: AsyncSession) -> User:
    """Idempotently return a demo user in DEBUG mode.

    Uses a unique key (email) and handles race conditions by catching
    IntegrityError and re-selecting the created row.
    Assigns admin role to demo user for full access.
    """
    # Always target the dedicated demo identity
    demo_email = "demo@example.com"
    # Eagerly load roles to avoid lazy loading in async context
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == demo_email)
    )
    user = result.scalar_one_or_none()
    if user:
        set_actor_id(user.id)
        return user

    # Create demo user
    demo = User(
        email=demo_email,
        username="demo",
        full_name="Demo User",
        hashed_password=get_password_hash("demo"),
        is_active=True,
        is_superuser=False,
    )
    db.add(demo)

    try:
        await db.commit()

        # Re-fetch with roles eagerly loaded to avoid lazy loading issues
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.email == demo_email)
        )
        demo = result.scalar_one()

        # Assign admin role to demo user
        admin_role_result = await db.execute(select(Role).where(Role.name == "admin"))
        admin_role = admin_role_result.scalar_one_or_none()

        if admin_role and admin_role not in demo.roles:
            demo.roles.append(admin_role)
            await db.commit()
            # Re-fetch again with updated roles
            result = await db.execute(
                select(User).options(selectinload(User.roles)).where(User.email == demo_email)
            )
            demo = result.scalar_one()

        return demo
    except IntegrityError:
        # Another concurrent worker created it — rollback and fetch
        await db.rollback()
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.email == demo_email)
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        # If still not there, bubble up
        raise


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> User:
    """Resolve the current user from the Authorization header."""
    return await _resolve_current_user(
        db,
        authorization=authorization,
        allow_debug_demo_fallback=True,
    )


async def _resolve_current_user(
    db: AsyncSession,
    *,
    authorization: Optional[str],
    allow_debug_demo_fallback: bool,
) -> User:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        with handle_api_error(operation="decode_token", status_code=status.HTTP_401_UNAUTHORIZED):
            payload = decode_token(token)
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        set_token_scopes(_normalize_token_scopes(payload.get("scopes")))
        set_token_tenant_id(_normalize_tenant_id(payload.get("tenant_id")))
        set_actor_id(user.id)
        return user

    _clear_auth_context()

    if allow_debug_demo_fallback and settings.DEBUG:
        user = await _get_or_create_demo_user(db)
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
        user = result.scalar_one()
        set_actor_id(user.id)
        return user

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


async def get_current_user_strict(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> User:
    """Resolve the current user without DEBUG/demo fallback."""
    return await _resolve_current_user(
        db,
        authorization=authorization,
        allow_debug_demo_fallback=False,
    )


async def require_integration_access(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> User | None:
    """
    Require a real authenticated user for integration endpoints unless the
    explicit unauthenticated local-demo bypass is enabled.
    """
    if (
        settings.ALLOW_UNAUTHENTICATED_DEMO_API
        and not authorization
        and request is not None
        and _is_local_demo_request(request)
    ):
        _clear_auth_context()
        return None

    if settings.ALLOW_UNAUTHENTICATED_DEMO_API and not authorization:
        logger.warning(
            "Rejected unauthenticated integration access outside local-demo request boundary: client=%s host=%s origin=%s",
            request.client.host if request and request.client else None,
            request.headers.get("host") if request else None,
            request.headers.get("origin") if request else None,
        )

    return await _resolve_current_user(
        db,
        authorization=authorization,
        allow_debug_demo_fallback=False,
    )


async def ensure_project_access(
    project_id: int,
    db: AsyncSession,
    current_user: User,
) -> Project:
    """Ensure the target project exists and is accessible to the current user."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Check user is active
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    if can_access_project(project, current_user):
        return project

    token_tenant_id = get_token_tenant_id()
    project_tenant_id = _project_tenant_id(project)
    if project_tenant_id is not None or token_tenant_id is not None:
        if token_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant-scoped token is required",
            )
        if project_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project tenant mismatch",
            )
        if str(token_tenant_id) != str(project_tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project tenant mismatch",
            )

    # Deny by default unless the caller is the owner or an explicit member.
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project access denied")


def require_permission(permission: str):
    """
    Dependency that checks if the current user has a specific permission.

    Usage:
        @router.post("/projects")
        async def create_project(
            user: User = Depends(require_permission(Permissions.PROJECT_CREATE))
        ):
            ...

    Args:
        permission: Permission string (e.g., Permissions.PROJECT_CREATE)

    Returns:
        Dependency function that returns the current user if they have the permission

    Raises:
        HTTPException 403: If user doesn't have the required permission
    """

    async def _check_permission(current_user: User = Depends(get_current_user)) -> User:
        token_scopes = get_token_scopes()
        if (
            token_scopes is not None
            and permission not in token_scopes
            and Permissions.ADMIN not in token_scopes
        ):
            logger.warning(
                "Scoped permission denied: user=%s (id=%s) attempted %s with scopes=%s",
                current_user.email,
                current_user.id,
                permission,
                ",".join(token_scopes),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission}",
            )

        if token_scopes is None and not current_user.has_permission(permission):
            logger.warning(
                "Permission denied: user=%s (id=%s) attempted %s",
                current_user.email,
                current_user.id,
                permission,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission}",
            )
        return current_user

    return _check_permission
