from datetime import timedelta
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, verify_password, get_password_hash
from app.core.rate_limit import limiter
from app.models import User
from app.schemas.user import Token, UserCreate, User as UserSchema
from app.utils import execute_with_lock

router = APIRouter()


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
) -> Any:
    """OAuth2 compatible token login"""
    result = await db.execute(
        select(User).where(User.email == form_data.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )

    # Validate via response model, then return as Response for SlowAPI headers
    token_payload = Token(access_token=access_token, token_type="bearer").model_dump()
    return JSONResponse(content=token_payload)


@router.post("/register", response_model=UserSchema)
async def register(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """Register new user"""
    try:
        async with db.begin():
            # Pre-flight unique checks with optional row-level lock
            sel_email = select(User).where(User.email == user_in.email)
            if (await execute_with_lock(db, sel_email)).scalar_one_or_none():
                raise HTTPException(status_code=400, detail="User with this email already exists")

            sel_username = select(User).where(User.username == user_in.username)
            if (await execute_with_lock(db, sel_username)).scalar_one_or_none():
                raise HTTPException(status_code=400, detail="User with this username already exists")

            # Create new user — never allow client to self-assign superuser
            user = User(
                email=user_in.email,
                username=user_in.username,
                full_name=user_in.full_name,
                hashed_password=get_password_hash(user_in.password),
                is_active=True,
                is_superuser=False,
            )
            db.add(user)
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="User with this email or username already exists")
    
    return user
