from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, status
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
    return bool(
        current_user.is_superuser
        or current_user.has_permission(Permissions.ADMIN)
        or (token_scopes is not None and Permissions.ADMIN in token_scopes)
    )


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
    """Resolve the current user from the Authorization header.

    Falls back to a demo user in development environments when no token is supplied.
    Eagerly loads user roles for permission checking.
    """
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
        with handle_api_error(operation="decode_token", status_code=status.HTTP_401_UNAUTHORIZED):
            payload = decode_token(token)
        email = payload.get("sub")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        # Eagerly load roles for permission checking
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
    # In non-debug environments, require a valid token; do not auto-create demo users.
    if settings.DEBUG:
        user = await _get_or_create_demo_user(db)
        # Eagerly load roles for permission checking
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
        user = result.scalar_one()
        set_token_scopes(None)
        set_token_tenant_id(None)
        set_actor_id(user.id)
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


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

    if _is_admin_access(current_user):
        return project

    project_meta = _project_meta(project)
    token_tenant_id = get_token_tenant_id()
    project_tenant_id = project_meta.get("tenant_id")
    if token_tenant_id is not None and project_tenant_id is not None:
        if str(token_tenant_id) != str(project_tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Project tenant mismatch",
            )

    if project.owner_id == current_user.id:
        return project

    if current_user.id in _project_member_ids(project):
        return project

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
