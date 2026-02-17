from datetime import timedelta
import logging
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, verify_password, get_password_hash
from app.core.rate_limit import limiter
from app.core.oauth import (
    google_oauth,
    microsoft_oauth,
    OAuth2Error,
    OAuth2UserInfo,
    get_oauth_providers,
    is_email_allowed,
)
from app.core.mfa import (
    setup_mfa,
    verify_totp,
    verify_backup_code,
    generate_backup_codes,
    hash_backup_codes,
)
from app.models import User, Role
from app.schemas.user import Token, UserCreate, User as UserSchema
from app.utils import execute_with_lock
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_default_role(db: AsyncSession, is_first_user: bool) -> Role | None:
    """Resolve bootstrap role for newly created users."""
    preferred_role = "admin" if is_first_user else "po"
    result = await db.execute(select(Role).where(Role.name == preferred_role))
    role = result.scalar_one_or_none()

    if role is None:
        fallback = await db.execute(select(Role).where(Role.name == "viewer"))
        role = fallback.scalar_one_or_none()

    return role


@router.post("/login")
@limiter.limit("5/minute")
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    OAuth2 compatible token login.

    If MFA is enabled, returns mfa_required=True with a temporary token.
    The client must then call /auth/mfa/verify-login to complete authentication.
    """
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()

    if (
        not user
        or not user.hashed_password
        or not verify_password(form_data.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Check if MFA is enabled
    if user.mfa_enabled:
        # Issue a short-lived temporary token for MFA verification
        temp_token = create_access_token(
            data={"sub": user.email, "type": "mfa_pending"},
            expires_delta=timedelta(minutes=5),  # Short-lived
        )
        return JSONResponse(
            content={
                "mfa_required": True,
                "temp_token": temp_token,
                "message": "MFA verification required",
            }
        )

    # No MFA - issue regular access token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.email}, expires_delta=access_token_expires)

    # Validate via response model, then return as Response for SlowAPI headers
    token_payload = Token(access_token=access_token, token_type="bearer").model_dump()
    return JSONResponse(content=token_payload)


@router.post("/register", response_model=UserSchema)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    """Register a new user with a default role."""
    user: User | None = None
    try:
        async with db.begin():
            sel_email = select(User).where(User.email == user_in.email)
            if (await execute_with_lock(db, sel_email)).scalar_one_or_none():
                raise HTTPException(status_code=400, detail="User with this email already exists")

            sel_username = select(User).where(User.username == user_in.username)
            if (await execute_with_lock(db, sel_username)).scalar_one_or_none():
                raise HTTPException(
                    status_code=400, detail="User with this username already exists"
                )

            users_count_result = await db.execute(select(func.count(User.id)))
            is_first_user = (users_count_result.scalar_one() or 0) == 0
            default_role = await _get_default_role(db, is_first_user=is_first_user)

            user = User(
                email=user_in.email,
                username=user_in.username,
                full_name=user_in.full_name,
                hashed_password=get_password_hash(user_in.password),
                is_active=True,
                is_superuser=False,
            )
            if default_role is not None:
                user.roles = [default_role]
            db.add(user)
            await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=400, detail="User with this email or username already exists"
        )

    if user is None:
        raise HTTPException(status_code=500, detail="Failed to create user")

    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.id == user.id)
    )
    user_with_roles = result.scalar_one()
    return user_with_roles

# =============================================================================
# OAuth2 SSO Endpoints
# =============================================================================


class OAuth2AuthURL(BaseModel):
    """Response containing OAuth2 authorization URL."""

    authorization_url: str
    state: str


class OAuth2ProvidersResponse(BaseModel):
    """Response listing available OAuth2 providers."""

    google: bool
    microsoft: bool


@router.get("/oauth2/providers", response_model=OAuth2ProvidersResponse)
async def get_available_providers() -> OAuth2ProvidersResponse:
    """Get list of available and configured OAuth2 providers."""
    providers = get_oauth_providers()
    return OAuth2ProvidersResponse(**providers)


# -----------------------------------------------------------------------------
# Google OAuth2
# -----------------------------------------------------------------------------


@router.get("/oauth2/google", response_model=OAuth2AuthURL)
async def google_oauth_start(
    redirect_uri: Optional[str] = Query(None, description="Override default redirect URI"),
) -> OAuth2AuthURL:
    """
    Initiate Google OAuth2 authentication flow.
    Returns authorization URL for frontend to redirect user.
    """
    try:
        if redirect_uri:
            client = type(google_oauth)(redirect_uri=redirect_uri)
            auth_url, state = client.get_authorization_url()
        else:
            auth_url, state = google_oauth.get_authorization_url()
        return OAuth2AuthURL(authorization_url=auth_url, state=state)
    except OAuth2Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth2 not configured: {e.description}",
        )


@router.get("/oauth2/google/callback")
async def google_oauth_callback(
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Handle Google OAuth2 callback.
    Exchanges code for tokens and creates/links user account.
    """
    try:
        # Exchange code for tokens
        token_response = await google_oauth.exchange_code(code)
        access_token = token_response.get("access_token")

        if not access_token:
            raise OAuth2Error("no_access_token", "Token response missing access_token")

        # Get user info from Google
        user_info = await google_oauth.get_user_info(access_token)

        # Process OAuth login
        user = await _process_oauth_login(db, user_info)

        # Generate JWT token
        jwt_token = create_access_token(
            data={"sub": user.email},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        return Token(access_token=jwt_token, token_type="bearer")

    except OAuth2Error as e:
        logger.error(f"Google OAuth2 error: {e.error} - {e.description}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth2 authentication failed: {e.error}",
        )


# -----------------------------------------------------------------------------
# Microsoft OAuth2
# -----------------------------------------------------------------------------


@router.get("/oauth2/microsoft", response_model=OAuth2AuthURL)
async def microsoft_oauth_start(
    redirect_uri: Optional[str] = Query(None, description="Override default redirect URI"),
) -> OAuth2AuthURL:
    """
    Initiate Microsoft OAuth2 authentication flow.
    Returns authorization URL for frontend to redirect user.
    """
    try:
        if redirect_uri:
            client = type(microsoft_oauth)(redirect_uri=redirect_uri)
            auth_url, state = client.get_authorization_url()
        else:
            auth_url, state = microsoft_oauth.get_authorization_url()
        return OAuth2AuthURL(authorization_url=auth_url, state=state)
    except OAuth2Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Microsoft OAuth2 not configured: {e.description}",
        )


@router.get("/oauth2/microsoft/callback")
async def microsoft_oauth_callback(
    code: str = Query(..., description="Authorization code from Microsoft"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Handle Microsoft OAuth2 callback.
    Exchanges code for tokens and creates/links user account.
    """
    try:
        # Exchange code for tokens
        token_response = await microsoft_oauth.exchange_code(code)
        access_token = token_response.get("access_token")

        if not access_token:
            raise OAuth2Error("no_access_token", "Token response missing access_token")

        # Get user info from Microsoft Graph
        user_info = await microsoft_oauth.get_user_info(access_token)

        # Process OAuth login
        user = await _process_oauth_login(db, user_info)

        # Generate JWT token
        jwt_token = create_access_token(
            data={"sub": user.email},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        return Token(access_token=jwt_token, token_type="bearer")

    except OAuth2Error as e:
        logger.error(f"Microsoft OAuth2 error: {e.error} - {e.description}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth2 authentication failed: {e.error}",
        )


# -----------------------------------------------------------------------------
# OAuth2 Helper Functions
# -----------------------------------------------------------------------------


async def _process_oauth_login(db: AsyncSession, user_info: OAuth2UserInfo) -> User:
    """
    Process OAuth2 login by finding existing user or creating new one.

    Strategy:
    1. First check if user exists by OAuth provider + provider_id (returning user)
    2. Then check by email (linking OAuth to existing account)
    3. Finally create new user if email domain is allowed
    """
    # Check domain restrictions
    if not is_email_allowed(user_info.email):
        raise OAuth2Error("domain_not_allowed", "Email domain not allowed for registration")

    # Look for existing user by OAuth identity
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .where(User.oauth_provider == user_info.provider, User.oauth_id == user_info.provider_id)
    )
    user = result.scalar_one_or_none()

    if user:
        logger.info(f"OAuth login: returning user {user.email} via {user_info.provider}")
        return user

    # Look for existing user by email (link OAuth identity)
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == user_info.email)
    )
    user = result.scalar_one_or_none()

    if user:
        # Link OAuth identity to existing account
        user.oauth_provider = user_info.provider
        user.oauth_id = user_info.provider_id
        user.oauth_email = user_info.email
        if user_info.picture:
            user.avatar_url = user_info.picture
        await db.commit()
        await db.refresh(user, attribute_names=["roles"])
        logger.info(f"OAuth login: linked {user_info.provider} to existing user {user.email}")
        return user

    # Create new user from OAuth
    username = _generate_username_from_email(user_info.email)

    # Ensure username is unique
    base_username = username
    counter = 1
    while True:
        result = await db.execute(select(User).where(User.username == username))
        if not result.scalar_one_or_none():
            break
        username = f"{base_username}{counter}"
        counter += 1

    new_user = User(
        email=user_info.email,
        username=username,
        full_name=user_info.name,
        hashed_password=None,  # OAuth users don't have passwords initially
        is_active=True,
        is_superuser=False,
        oauth_provider=user_info.provider,
        oauth_id=user_info.provider_id,
        oauth_email=user_info.email,
        avatar_url=user_info.picture,
    )

    users_count_result = await db.execute(select(func.count(User.id)))
    is_first_user = (users_count_result.scalar_one() or 0) == 0
    default_role = await _get_default_role(db, is_first_user=is_first_user)

    if default_role is not None:
        new_user.roles = [default_role]
    db.add(new_user)
    await db.flush()
    await db.commit()
    await db.refresh(new_user, attribute_names=["roles"])
    logger.info(f"OAuth login: created new user {new_user.email} via {user_info.provider}")
    return new_user


def _generate_username_from_email(email: str) -> str:
    """Generate a username from email address."""
    local_part = email.split("@")[0]
    # Remove special characters, keep alphanumeric and underscores
    username = "".join(c if c.isalnum() or c == "_" else "_" for c in local_part)
    # Ensure it starts with a letter
    if username and not username[0].isalpha():
        username = "user_" + username
    return username[:50]  # Limit length


# =============================================================================
# Multi-Factor Authentication (MFA) Endpoints
# =============================================================================


class MFASetupResponse(BaseModel):
    """Response for MFA setup initialization."""

    secret: str = Field(..., description="TOTP secret (store securely)")
    qr_code: str = Field(..., description="Base64 QR code image for authenticator apps")
    provisioning_uri: str = Field(..., description="otpauth:// URI")
    backup_codes: List[str] = Field(..., description="One-time backup recovery codes")


class MFAVerifyRequest(BaseModel):
    """Request to verify MFA code."""

    code: str = Field(..., min_length=6, max_length=12, description="6-digit TOTP or backup code")


class MFAStatusResponse(BaseModel):
    """Response showing current MFA status."""

    mfa_enabled: bool
    mfa_configured: bool
    remaining_backup_codes: int


class MFABackupCodesResponse(BaseModel):
    """Response with regenerated backup codes."""

    backup_codes: List[str]


class MFALoginRequired(BaseModel):
    """Response indicating MFA verification is needed."""

    mfa_required: bool = True
    temp_token: str = Field(..., description="Temporary token for MFA verification")


@router.get("/mfa/status", response_model=MFAStatusResponse)
async def get_mfa_status(
    current_user: User = Depends(get_current_user),
) -> MFAStatusResponse:
    """
    Get current MFA status for the authenticated user.
    """
    return MFAStatusResponse(
        mfa_enabled=current_user.mfa_enabled,
        mfa_configured=current_user.mfa_configured,
        remaining_backup_codes=current_user.remaining_backup_codes,
    )


@router.post("/mfa/setup", response_model=MFASetupResponse)
@limiter.limit("3/minute")
async def initiate_mfa_setup(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MFASetupResponse:
    """
    Initialize MFA setup for the current user.

    Returns QR code and backup codes. User must verify with a TOTP code
    before MFA is actually enabled.
    """
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA is already enabled. Disable it first to reconfigure.",
        )

    # Generate new MFA setup data
    mfa_data = setup_mfa(current_user.email)

    # Store secret temporarily (will be confirmed on verify)
    # The secret is stored but mfa_enabled remains False until verified
    current_user.mfa_secret = mfa_data.secret
    current_user.mfa_backup_codes = hash_backup_codes(mfa_data.backup_codes)

    await db.commit()

    logger.info(f"MFA setup initiated for user {current_user.email}")

    return MFASetupResponse(
        secret=mfa_data.secret,
        qr_code=mfa_data.qr_code_base64,
        provisioning_uri=mfa_data.provisioning_uri,
        backup_codes=mfa_data.backup_codes,
    )


@router.post("/mfa/verify")
@limiter.limit("5/minute")
async def verify_mfa_setup(
    request: Request,
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Verify MFA setup with a TOTP code from the authenticator app.

    This confirms the user has correctly configured their authenticator
    and enables MFA on their account.
    """
    if current_user.mfa_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled"
        )

    if not current_user.mfa_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup not initiated. Call /mfa/setup first.",
        )

    secret = current_user.mfa_secret
    if not secret or not verify_totp(secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Please check your authenticator app.",
        )

    # Enable MFA
    current_user.mfa_enabled = True
    await db.commit()

    logger.info(f"MFA enabled for user {current_user.email}")

    return {
        "message": "MFA has been enabled successfully",
        "mfa_enabled": True,
        "remaining_backup_codes": current_user.remaining_backup_codes,
    }


@router.post("/mfa/disable")
@limiter.limit("3/minute")
async def disable_mfa(
    request: Request,
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Disable MFA for the current user.

    Requires verification with current TOTP code or backup code.
    """
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")

    secret = current_user.mfa_secret
    if not secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA secret missing")

    # Verify with TOTP or backup code
    code_valid = verify_totp(secret, body.code)

    if not code_valid and current_user.mfa_backup_codes:
        # Try backup code
        is_backup_valid, code_index = verify_backup_code(body.code, current_user.mfa_backup_codes)
        code_valid = is_backup_valid

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code"
        )

    # Disable MFA and clear secrets
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_backup_codes = None

    await db.commit()

    logger.info(f"MFA disabled for user {current_user.email}")

    return {
        "message": "MFA has been disabled",
        "mfa_enabled": False,
    }


@router.post("/mfa/backup-codes/regenerate", response_model=MFABackupCodesResponse)
@limiter.limit("2/minute")
async def regenerate_backup_codes(
    request: Request,
    body: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MFABackupCodesResponse:
    """
    Regenerate MFA backup codes.

    Requires verification with current TOTP code.
    Invalidates all previous backup codes.
    """
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")

    secret = current_user.mfa_secret
    if not secret or not verify_totp(secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code. Use your authenticator app code.",
        )

    # Generate new backup codes
    new_codes = generate_backup_codes()
    current_user.mfa_backup_codes = hash_backup_codes(new_codes)

    await db.commit()

    logger.info(f"Backup codes regenerated for user {current_user.email}")

    return MFABackupCodesResponse(backup_codes=new_codes)


@router.post("/mfa/verify-login")
@limiter.limit("5/minute")
async def verify_mfa_login(
    request: Request,
    body: MFAVerifyRequest,
    temp_token: str = Query(..., description="Temporary token from login"),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Complete login by verifying MFA code.

    Called after initial login returns mfa_required=True.
    Accepts either TOTP code or backup code.
    """
    from app.core.security import decode_token

    # Decode the temporary token
    try:
        payload = decode_token(temp_token)
        if payload.get("type") != "mfa_pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid temporary token"
            )
        email = payload.get("sub")
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired temporary token"
        )

    # Get user
    result = await db.execute(
        select(User).options(selectinload(User.roles)).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    if not user or not user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid request")

    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA secret missing")

    # Try TOTP verification
    code_valid = verify_totp(user.mfa_secret, body.code)

    # If TOTP fails, try backup code
    if not code_valid and user.mfa_backup_codes:
        is_backup_valid, code_index = verify_backup_code(body.code, user.mfa_backup_codes)
        if is_backup_valid and code_index is not None:
            # Remove used backup code
            codes = list(user.mfa_backup_codes)
            codes.pop(code_index)
            user.mfa_backup_codes = codes
            await db.commit()
            code_valid = True
            logger.info(f"MFA login with backup code for user {email}")

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid verification code"
        )

    # Generate full access token
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    logger.info(f"MFA login completed for user {email}")

    return Token(access_token=access_token, token_type="bearer")

