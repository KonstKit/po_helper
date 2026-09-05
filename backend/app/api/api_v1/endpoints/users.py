from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.models import User, Role, Permissions
from app.schemas.user import User as UserSchema, UserUpdate, PasswordChange
from app.core.security import verify_password, get_password_hash
from app.api.deps import get_current_user, require_permission
from app.utils import paginate_query, get_or_404, execute_with_lock

router = APIRouter()


@router.get("/", response_model=List[UserSchema])
async def get_users(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
) -> List[User]:
    """Return paginated list of users."""
    query = select(User).options(selectinload(User.roles))
    return await paginate_query(db, query, skip, limit)


@router.get("/id/{user_id}", response_model=UserSchema)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Fetch a user by identifier."""
    query = select(User).options(selectinload(User.roles)).where(User.id == user_id)
    user = await get_or_404(db, query, "User")
    return user


@router.patch("/id/{user_id}", response_model=UserSchema)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Update mutable fields on a user by ID."""
    query = select(User).options(selectinload(User.roles)).where(User.id == user_id)
    user = await get_or_404(db, query, "User")

    update_data = user_update.dict(exclude_unset=True)
    update_data.pop("email", None)
    try:
        async with db.begin():
            # Enforce username uniqueness if it is being updated
            if "username" in update_data and update_data["username"]:
                sel = (
                    select(User)
                    .where(User.username == update_data["username"])
                    .where(User.id != user_id)
                )
                if (await execute_with_lock(db, sel)).scalar_one_or_none():
                    raise HTTPException(
                        status_code=400, detail="User with this username already exists"
                    )
            for field, value in update_data.items():
                setattr(user, field, value)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User with this username already exists")
    await db.refresh(user)
    return user


@router.get("/me", response_model=UserSchema)
async def get_current_user_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> User:
    """Return the profile for the authenticated user (demo fallback in dev)."""
    return await get_current_user(request=request, db=db, authorization=authorization)


@router.patch("/me", response_model=UserSchema)
async def update_current_user(
    user_update: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> User:
    user = await get_current_user(request=request, db=db, authorization=authorization)
    update_data = user_update.dict(exclude_unset=True)
    update_data.pop("email", None)
    update_data.pop("is_superuser", None)
    update_data.pop("is_active", None)
    try:
        async with db.begin():
            if "username" in update_data and update_data["username"]:
                sel = (
                    select(User)
                    .where(User.username == update_data["username"])
                    .where(User.id != user.id)
                )
                if (await execute_with_lock(db, sel)).scalar_one_or_none():
                    raise HTTPException(
                        status_code=400, detail="User with this username already exists"
                    )
            for field, value in update_data.items():
                setattr(user, field, value)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User with this username already exists")
    await db.refresh(user)
    return user


@router.post("/me/password")
async def change_password(
    payload: PasswordChange,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> dict:
    user = await get_current_user(request=request, db=db, authorization=authorization)
    if not user.hashed_password or not verify_password(
        payload.current_password, user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.hashed_password = get_password_hash(payload.new_password)
    await db.commit()
    return {"message": "Password updated"}


@router.post("/id/{user_id}/roles/{role_id}")
async def assign_role_to_user(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.USER_MANAGE_ROLES)),
) -> dict:
    """Assign a role to a user (admin only)."""
    # Get user with eager-loaded roles to avoid async lazy loading issues
    query = select(User).options(selectinload(User.roles)).where(User.id == user_id)
    user = await get_or_404(db, query, "User")

    # Get role
    role = await get_or_404(db, select(Role).where(Role.id == role_id), "Role")

    # Check if already assigned
    if role in user.roles:
        raise HTTPException(status_code=400, detail="User already has this role")

    # Assign role
    user.roles.append(role)
    await db.commit()

    return {"message": f"Role '{role.name}' assigned to user '{user.username}'"}


@router.delete("/id/{user_id}/roles/{role_id}")
async def remove_role_from_user(
    user_id: int,
    role_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.USER_MANAGE_ROLES)),
) -> dict:
    """Remove a role from a user (admin only)."""
    # Get user with eager-loaded roles to avoid async lazy loading issues
    query = select(User).options(selectinload(User.roles)).where(User.id == user_id)
    user = await get_or_404(db, query, "User")

    # Get role
    role = await get_or_404(db, select(Role).where(Role.id == role_id), "Role")

    # Check if assigned
    if role not in user.roles:
        raise HTTPException(status_code=400, detail="User does not have this role")

    # Remove role
    user.roles.remove(role)
    await db.commit()

    return {"message": f"Role '{role.name}' removed from user '{user.username}'"}
