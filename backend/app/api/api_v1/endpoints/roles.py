"""
Role management endpoints.

Provides CRUD operations for roles (admin only).
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import Role, User, Permissions
from app.schemas.user import Role as RoleSchema, RoleCreate
from app.api.deps import require_permission
from app.utils import transactional_session, get_or_404

router = APIRouter()


@router.get("/", response_model=List[RoleSchema])
async def get_roles(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.ADMIN))
) -> List[Role]:
    """Get all roles (admin only)."""
    result = await db.execute(select(Role))
    return result.scalars().all()


@router.get("/{role_id}", response_model=RoleSchema)
async def get_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.ADMIN))
) -> Role:
    """Get role by ID (admin only)."""
    role = await get_or_404(db, select(Role).where(Role.id == role_id), "Role")
    return role


@router.post("/", response_model=RoleSchema)
async def create_role(
    role: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.ADMIN))
) -> Role:
    """Create a new custom role (admin only)."""
    # Check if role name already exists
    result = await db.execute(select(Role).where(Role.name == role.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Role with this name already exists")

    db_role = Role(
        name=role.name,
        display_name=role.display_name,
        description=role.description,
        is_system=False,  # Custom roles are not system roles
        permissions=role.permissions,
    )
    async with transactional_session(db):
        db.add(db_role)
    await db.refresh(db_role)
    return db_role


@router.delete("/{role_id}")
async def delete_role(
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.ADMIN))
) -> dict:
    """Delete a custom role (admin only). System roles cannot be deleted."""
    role = await get_or_404(db, select(Role).where(Role.id == role_id), "Role")

    if role.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system roles")

    async with transactional_session(db):
        await db.delete(role)
    return {"message": f"Role '{role.name}' deleted successfully"}
