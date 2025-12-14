from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.core.database import get_db
from app.core.security import decode_token, get_password_hash
from sqlalchemy.exc import IntegrityError
logger = logging.getLogger(__name__)

from app.models import User, Project, Role, Permissions
from app.core.config import settings
from sqlalchemy.orm import selectinload
from app.utils import handle_api_error


async def _get_or_create_demo_user(db: AsyncSession) -> User:
    """Idempotently return a demo user in DEBUG mode.

    Uses a unique key (email) and handles race conditions by catching
    IntegrityError and re-selecting the created row.
    Assigns admin role to demo user for full access.
    """
    # Always target the dedicated demo identity
    demo_email = "demo@example.com"
    result = await db.execute(select(User).where(User.email == demo_email))
    user = result.scalar_one_or_none()
    if user:
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
        await db.refresh(demo)

        # Assign admin role to demo user
        admin_role_result = await db.execute(select(Role).where(Role.name == 'admin'))
        admin_role = admin_role_result.scalar_one_or_none()

        if admin_role and admin_role not in demo.roles:
            demo.roles.append(admin_role)
            await db.commit()
            await db.refresh(demo)

        return demo
    except IntegrityError:
        # Another concurrent worker created it — rollback and fetch
        await db.rollback()
        result = await db.execute(select(User).where(User.email == demo_email))
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
        with handle_api_error(
            operation="decode_token",
            status_code=status.HTTP_401_UNAUTHORIZED
        ):
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
        return user
    # In non-debug environments, require a valid token; do not auto-create demo users.
    if settings.DEBUG:
        user = await _get_or_create_demo_user(db)
        # Eagerly load roles for permission checking
        result = await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
        user = result.scalar_one()
        return user
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Not authenticated')


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

    return project


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
    async def _check_permission(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if not current_user.has_permission(permission):
            logger.warning(
                "Permission denied: user=%s (id=%s) attempted %s",
                current_user.email,
                current_user.id,
                permission
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {permission}"
            )
        return current_user

    return _check_permission


def require_role(role_name: str):
    """
    Dependency that checks if the current user has a specific role.

    Usage:
        @router.get("/admin/users")
        async def list_all_users(
            user: User = Depends(require_role("admin"))
        ):
            ...

    Args:
        role_name: Role name (e.g., 'admin', 'po')

    Returns:
        Dependency function that returns the current user if they have the role

    Raises:
        HTTPException 403: If user doesn't have the required role
    """
    async def _check_role(
        current_user: User = Depends(get_current_user)
    ) -> User:
        if not current_user.has_role(role_name):
            logger.warning(
                "Role check failed: user=%s (id=%s) attempted role=%s",
                current_user.email,
                current_user.id,
                role_name
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {role_name}"
            )
        return current_user

    return _check_role


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency that ensures the user is active.

    This is a simpler alternative to get_current_user for endpoints that don't need
    permission checking but want to ensure the user is active.

    Usage:
        @router.get("/me")
        async def get_me(user: User = Depends(get_current_active_user)):
            ...
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user
