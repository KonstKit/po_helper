from datetime import datetime, timedelta, timezone
import hmac
import logging
from typing import Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, or_
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
from app.core.oauth_state import (
    OAUTH_STATE_COOKIE,
    OAuthStateError,
    create_oauth_state,
    validate_redirect_uri_override,
    verify_oauth_state,
)
from app.core.ws_tickets import issue_ws_ticket
from app.core.auth_cookies import (
    clear_auth_cookie,
    clear_refresh_cookie,
    get_refresh_cookie_token,
    set_auth_cookie,
    set_refresh_cookie,
)
from app.core.token_sessions import (
    create_token_session,
    get_active_session_by_token,
    get_session_by_token_any_state,
    new_refresh_token,
    revoke_all_user_sessions,
    revoke_session,
)
from app.core.crypto import AES_GCM_PREFIX
from app.core.mfa import (
    setup_mfa,
    verify_totp_with_counter,
    verify_backup_code,
    generate_backup_codes,
    hash_backup_codes,
    encrypt_mfa_secret,
    decrypt_mfa_secret,
)
from app.core.mfa import _is_kdf_backup_code
from app.core.request_context import get_token_scopes, get_token_tenant_id
from app.models import User, Role, Project
from app.models.token_session import TokenSession
from app.models.rbac import Permissions
from app.schemas.user import (
    ScopedTokenRequest,
    Token,
    UserCreate,
    User as UserSchema,
)
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


def _normalize_scopes(scopes: list[str]) -> list[str]:
    normalized: list[str] = []
    for scope in scopes:
        if not isinstance(scope, str):
            continue  # type: ignore[unreachable]
        cleaned = scope.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _project_meta(meta: Any) -> dict[str, Any]:
    if isinstance(meta, dict):
        return meta
    return {}


def _project_member_ids(meta: dict[str, Any]) -> set[int]:
    member_ids: set[int] = set()
    raw_member_ids = meta.get("member_ids")
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


async def _user_has_access_to_tenant(
    db: AsyncSession,
    *,
    user_id: int,
    tenant_id: str,
) -> bool:
    tenant_filter = Project.meta["tenant_id"].as_string() == tenant_id

    # Fast path: owner projects for this user.
    owned_result = await db.execute(
        select(Project.id)
        .where(
            Project.owner_id == user_id,
            Project.meta.is_not(None),
            tenant_filter,
        )
        .limit(1)
    )
    if owned_result.scalar_one_or_none() is not None:
        return True

    # Membership path: DB narrows to tenant, Python validates member_ids payload.
    member_result = await db.execute(
        select(Project.meta).where(
            Project.meta.is_not(None),
            tenant_filter,
        )
    )
    for (project_meta,) in member_result.all():
        meta = _project_meta(project_meta)
        if user_id in _project_member_ids(meta):
            return True

    return False


def _effective_permissions(user: User) -> set[str]:
    permissions: set[str] = set()
    user_roles = getattr(user, "roles", None) or []
    for role in user_roles:
        permissions.update(getattr(role, "permissions", []) or [])

    if not permissions:
        # Keep compatibility with lightweight test doubles that expose only has_permission().
        for attr in dir(Permissions):
            if not attr.isupper():
                continue
            value = getattr(Permissions, attr, None)
            if isinstance(value, str) and user.has_permission(value):
                permissions.add(value)
    return permissions


async def _issue_refresh_session(
    db: AsyncSession,
    user: User,
    request: Request,
) -> str:
    """Create a server-side session and return the plaintext refresh token."""
    refresh_token, _ = new_refresh_token()
    await create_token_session(
        db,
        user_id=user.id,
        refresh_token=refresh_token,
        user_agent=request.headers.get("user-agent"),
    )
    return refresh_token


@router.post("/login")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> JSONResponse:
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

    # M3: server-side refresh session (rotation + revocation).
    refresh_token = await _issue_refresh_session(db, user, request)
    await db.commit()  # token_sessions row must survive the request

    # Dual mode (M1): body token still returned for backward compat.
    """The httpOnly cookie is the browser session."""
    token_payload = Token(access_token=access_token, token_type="bearer").model_dump()
    token_payload["refresh_token"] = refresh_token
    response = JSONResponse(content=token_payload)
    set_refresh_cookie(response, refresh_token)
    set_auth_cookie(response, access_token)
    return response


class WSTicketResponse(BaseModel):
    """Single-use ticket for the WebSocket handshake (see app/core/ws_tickets.py)."""

    ticket: str
    expires_in: int


@router.post("/ws-ticket", response_model=WSTicketResponse)
async def issue_websocket_ticket(
    response: Response,
    current_user: User = Depends(get_current_user),
) -> WSTicketResponse:
    """Exchange the caller's JWT for a one-time WS ticket.

    Browsers cannot set headers on a WebSocket handshake; passing this
    short-lived ticket in the query string keeps the long-lived JWT out
    of URLs (proxy/access logs, DevTools network capture).
    """
    ticket = issue_ws_ticket(current_user.email)
    response.headers["Cache-Control"] = "no-store"
    return WSTicketResponse(ticket=ticket, expires_in=60)


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    response = JSONResponse(content={"detail": "Logged out"})
    clear_auth_cookie(response)
    # M3: revoke the presented refresh session (from body or cookie) and
    # always clear the refresh cookie on logout.
    body_token = None
    try:
        body = await request.json()
    except Exception:
        logger.debug("logout: no JSON body (cookie-only logout)")
        body = None
    if isinstance(body, dict):
        candidate = body.get("refresh_token")
        if isinstance(candidate, str):
            body_token = candidate
    cookie_token = get_refresh_cookie_token(request)
    presented = body_token or cookie_token
    if presented:
        session = await get_active_session_by_token(db, presented)
        if session:
            await revoke_session(db, session)
            await db.commit()
    clear_refresh_cookie(response)
    return response


class RefreshRequest(BaseModel):
    # Optional body: browsers authenticate by the httpOnly refresh
    # cookie alone and send no body at all (M2).
    refresh_token: str = ""


@router.post("/refresh")
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def refresh(
    request: Request,
    body: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Rotate a refresh token: revoke the presented session and issue a
    new access token + a fresh refresh token session (M3).
    Reuse of a rotated/revoked token revokes the whole family
    (token reuse = potential theft)."""
    from app.core.token_sessions import (
        create_token_session,
        get_active_session_by_token,
        new_refresh_token,
    )

    presented = (body.refresh_token if body else "") or get_refresh_cookie_token(request)
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )
    session = await get_active_session_by_token(db, presented)
    if session is None:
        # Reuse of a rotated/revoked token is a theft signal: find the
        # family owner by hash (any state) and revoke every live session
        # of that user before rejecting. A merely EXPIRED token (never
        # revoked) is a benign sign-out: reject without family revocation.
        known = await get_session_by_token_any_state(db, presented)
        if known is not None and known.revoked_at is not None:
            await revoke_all_user_sessions(db, known.user_id)
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
        )

    # Atomic claim: conditional UPDATE wins exactly once even under
    # concurrent rotations of the same token.
    claimed = await db.execute(
        update(TokenSession)
        .where(
            TokenSession.id == session.id,
            TokenSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    if claimed.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    session.last_used_at = datetime.now(timezone.utc)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=access_token_expires,
    )
    refresh_token, _ = new_refresh_token()
    await create_token_session(
        db,
        user_id=user.id,
        refresh_token=refresh_token,
        user_agent=request.headers.get("user-agent"),
    )
    await db.commit()

    payload = Token(access_token=access_token, token_type="bearer").model_dump()
    payload["refresh_token"] = refresh_token
    response = JSONResponse(content=payload)
    set_refresh_cookie(response, refresh_token)
    set_auth_cookie(response, access_token)
    return response


@router.get("/sessions")
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """List the caller's live (unrevoked, unexpired) sessions (M3)."""
    from datetime import datetime, timezone
    from app.models.token_session import TokenSession

    cutoff = datetime.now(timezone.utc)
    result = await db.execute(
        select(TokenSession).where(
            TokenSession.user_id == current_user.id,
            TokenSession.revoked_at.is_(None),
            cutoff < TokenSession.expires_at,
        )
    )
    sessions = [
        {
            "id": s.id,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
            "user_agent": s.user_agent,
        }
        for s in result.scalars()
    ]
    return JSONResponse(content={"sessions": sessions, "count": len(sessions)})


@router.delete("/sessions/{session_id}")
async def revoke_session_endpoint(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> JSONResponse:
    """Revoke one of the caller's sessions (logout everywhere, per device)."""
    from app.models.token_session import TokenSession

    result = await db.execute(
        select(TokenSession).where(
            TokenSession.id == session_id,
            TokenSession.user_id == current_user.id,
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    await revoke_session(db, session)
    await db.commit()
    return JSONResponse(content={"detail": "Session revoked"})


@router.post("/scoped-token", response_model=Token)
async def issue_scoped_token(
    body: ScopedTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Token:
    """Issue a JWT restricted to the requested scopes for the current user."""
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")

    requested_scopes = _normalize_scopes(body.scopes)
    caller_token_scopes = get_token_scopes()
    caller_token_tenant_id = get_token_tenant_id()
    tenant_id = body.tenant_id.strip() if body.tenant_id else None
    caller_has_admin = (
        current_user.has_permission(Permissions.ADMIN)
        if caller_token_scopes is None
        else (Permissions.ADMIN in caller_token_scopes)
    )

    if body.tenant_id is not None and not tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tenant_id")

    # Never allow a scoped token to mint a different tenant context than the caller token.
    if caller_token_tenant_id is not None:
        if tenant_id is not None and tenant_id != caller_token_tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requested tenant_id does not match caller token tenant",
            )
        tenant_id = caller_token_tenant_id
    elif tenant_id is not None and not caller_has_admin:
        tenant_access = await _user_has_access_to_tenant(
            db,
            user_id=current_user.id,
            tenant_id=tenant_id,
        )
        if not tenant_access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requested tenant_id is not accessible for current user",
            )

    max_scoped_ttl = max(1, int(settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    if body.expires_minutes > max_scoped_ttl:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"expires_minutes cannot exceed {max_scoped_ttl}",
        )

    if not caller_has_admin:
        effective_permissions = _effective_permissions(current_user)
        if caller_token_scopes is not None:
            effective_permissions &= set(caller_token_scopes)
        invalid_scopes = [scope for scope in requested_scopes if scope not in effective_permissions]
        if invalid_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Requested scopes exceed your effective permissions",
            )

    access_token = create_access_token(
        data={
            "sub": current_user.email,
            "scopes": requested_scopes,
            "tenant_id": tenant_id,
        },
        expires_delta=timedelta(minutes=body.expires_minutes),
    )
    return Token(access_token=access_token, token_type="bearer")


@router.post("/register", response_model=UserSchema)
@limiter.limit("3/minute")
async def register(
    request: Request,
    response: Response,
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
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
    request: Request,
    response: Response,
    redirect_uri: Optional[str] = Query(None, description="Override default redirect URI"),
) -> OAuth2AuthURL:
    """
    Initiate Google OAuth2 authentication flow.
    Returns authorization URL for frontend to redirect user.
    """
    try:
        override = validate_redirect_uri_override(redirect_uri)
        client = type(google_oauth)(redirect_uri=override) if override else google_oauth
        state = create_oauth_state("google", redirect_uri=override)
        auth_url, _ = client.get_authorization_url(state=state)
        _set_oauth_state_cookie(response, state, request)
        return OAuth2AuthURL(authorization_url=auth_url, state=state)
    except OAuthStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"redirect_uri not allowed: {e}",
        )
    except OAuth2Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth2 not configured: {e.description}",
        )


@router.get("/oauth2/google/callback")
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from Google"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Handle Google OAuth2 callback.
    Exchanges code for tokens and creates/links user account.
    """
    redirect_override = _verify_oauth_callback_state(request, response, state, "google")
    try:
        client = (
            type(google_oauth)(redirect_uri=redirect_override)
            if redirect_override
            else google_oauth
        )
        # Exchange code for tokens
        token_response = await client.exchange_code(code)
        access_token = token_response.get("access_token")

        if not access_token:
            raise OAuth2Error("no_access_token", "Token response missing access_token")

        # Get user info from Google
        user_info = await client.get_user_info(access_token)

        # Process OAuth login
        user = await _process_oauth_login(db, user_info)

        # Generate JWT token
        jwt_token = create_access_token(
            data={"sub": user.email},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        # M3: server-side refresh session for the OAuth login.
        refresh_token = await _issue_refresh_session(db, user, request)
        await db.commit()  # token_sessions row must survive the request
        payload = Token(access_token=jwt_token, token_type="bearer").model_dump()
        payload["refresh_token"] = refresh_token
        response = JSONResponse(content=payload)
        # Keep the state-cookie deletion (single-use binding cookie).
        _clear_oauth_state_cookie(response)
        set_refresh_cookie(response, refresh_token)
        set_auth_cookie(response, jwt_token)
        return response

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
    request: Request,
    response: Response,
    redirect_uri: Optional[str] = Query(None, description="Override default redirect URI"),
) -> OAuth2AuthURL:
    """
    Initiate Microsoft OAuth2 authentication flow.
    Returns authorization URL for frontend to redirect user.
    """
    try:
        override = validate_redirect_uri_override(redirect_uri)
        client = type(microsoft_oauth)(redirect_uri=override) if override else microsoft_oauth
        state = create_oauth_state("microsoft", redirect_uri=override)
        auth_url, _ = client.get_authorization_url(state=state)
        _set_oauth_state_cookie(response, state, request)
        return OAuth2AuthURL(authorization_url=auth_url, state=state)
    except OAuthStateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"redirect_uri not allowed: {e}",
        )
    except OAuth2Error as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Microsoft OAuth2 not configured: {e.description}",
        )


@router.get("/oauth2/microsoft/callback")
async def microsoft_oauth_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Authorization code from Microsoft"),
    state: str = Query(..., description="State parameter for CSRF protection"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Handle Microsoft OAuth2 callback.
    Exchanges code for tokens and creates/links user account.
    """
    redirect_override = _verify_oauth_callback_state(request, response, state, "microsoft")
    try:
        client = (
            type(microsoft_oauth)(redirect_uri=redirect_override)
            if redirect_override
            else microsoft_oauth
        )
        # Exchange code for tokens
        token_response = await client.exchange_code(code)
        access_token = token_response.get("access_token")

        if not access_token:
            raise OAuth2Error("no_access_token", "Token response missing access_token")

        # Get user info from Microsoft Graph
        user_info = await client.get_user_info(access_token)

        # Process OAuth login
        user = await _process_oauth_login(db, user_info)

        # Generate JWT token
        jwt_token = create_access_token(
            data={"sub": user.email},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        # M3: server-side refresh session for the OAuth login.
        refresh_token = await _issue_refresh_session(db, user, request)
        await db.commit()  # token_sessions row must survive the request
        payload = Token(access_token=jwt_token, token_type="bearer").model_dump()
        payload["refresh_token"] = refresh_token
        response = JSONResponse(content=payload)
        # Keep the state-cookie deletion (single-use binding cookie).
        _clear_oauth_state_cookie(response)
        set_refresh_cookie(response, refresh_token)
        set_auth_cookie(response, jwt_token)
        return response

    except OAuth2Error as e:
        logger.error(f"Microsoft OAuth2 error: {e.error} - {e.description}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth2 authentication failed: {e.error}",
        )


# -----------------------------------------------------------------------------
# OAuth2 Helper Functions
# -----------------------------------------------------------------------------


def _set_oauth_state_cookie(response: Response, state: str, request: Request) -> None:
    """Bind the OAuth state to the browser that started the flow."""
    # Behind a TLS-terminating proxy the ASGI scheme is http; trust the
    # forwarded protocol header so the cookie stays Secure in production.
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    scheme = (
        forwarded_proto.split(",")[0].strip().lower() if forwarded_proto else request.url.scheme
    )
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=settings.OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=scheme == "https",
        path="/",
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/")


def _verify_oauth_callback_state(
    request: Request, response: Response, state: str, provider: str
) -> Optional[str]:
    """Reject forged, expired, or cross-browser OAuth callbacks.

    Returns the redirect_uri the flow started with (None = client default),
    taken from the verified state payload.
    """
    try:
        payload = verify_oauth_state(state, provider=provider)
    except OAuthStateError as e:
        logger.warning("OAuth state validation failed (%s): %s", provider, e)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth2 state validation failed",
        )

    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not cookie_state or not hmac.compare_digest(cookie_state, state):
        logger.warning("OAuth state cookie mismatch (%s)", provider)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth2 state validation failed",
        )

    # Single-use: consume the binding cookie once the flow completes.
    _clear_oauth_state_cookie(response)
    return payload.get("redirect_uri")


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
        # Linking an OAuth identity to an existing password-account grants
        # login access by email alone, so it requires a provider-verified
        # email and an explicit opt-in.
        if not settings.OAUTH_ALLOW_EMAIL_LINKING:
            logger.warning(
                "OAuth login: refused linking %s to existing account %s "
                "(OAUTH_ALLOW_EMAIL_LINKING disabled)",
                user_info.provider,
                user.email,
            )
            raise OAuth2Error(
                "email_linking_disabled",
                "An account with this email already exists. Sign in with your password "
                "to link OAuth providers from your profile settings.",
            )
        if not user_info.email_verified:
            raise OAuth2Error(
                "email_not_verified",
                "Provider has not verified this email address; linking is not allowed",
            )
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
    if not user_info.email_verified:
        raise OAuth2Error(
            "email_not_verified",
            "Provider has not verified this email address; registration is not allowed",
        )
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
    """Request to verify MFA code (authenticated MFA management endpoints)."""

    code: str = Field(..., min_length=6, max_length=32, description="6-digit TOTP or backup code")


class MFALoginVerifyRequest(BaseModel):
    """Request to complete an MFA login (unauthenticated endpoint).

    Carries the mfa_pending token in the body so it never lands in URLs
    (proxy/access logs).
    """

    code: str = Field(..., min_length=6, max_length=32, description="6-digit TOTP or backup code")
    temp_token: str = Field(
        ...,
        min_length=1,
        description="Temporary mfa_pending token returned by the initial login",
    )


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


async def _upgrade_mfa_storage(db: AsyncSession, user: User) -> None:
    """Upgrade legacy plaintext MFA storage on first touch (wave B).

    Secrets written before encryption and backup codes written before
    hashing are migrated in place: the secret is re-encrypted, plaintext
    codes are replaced by their bcrypt digests. No invalidation needed -
    verification semantics are unchanged.
    """
    changed = False
    if user.mfa_secret and not user.mfa_secret.startswith(AES_GCM_PREFIX):
        user.mfa_secret = encrypt_mfa_secret(user.mfa_secret)
        changed = True
    if user.mfa_backup_codes and any(
        not _is_kdf_backup_code(code) for code in user.mfa_backup_codes
    ):
        user.mfa_backup_codes = hash_backup_codes(user.mfa_backup_codes)
        changed = True
    if changed:
        await db.commit()
        logger.info("Upgraded legacy MFA storage to encrypted/hashed for %s", user.email)


async def _claim_totp_counter(db: AsyncSession, user: User, accepted_counter: int | None) -> bool:
    """Atomically claim a TOTP interval for anti-replay.

    A conditional UPDATE (not a read-modify-write of the ORM attribute)
    so two concurrent verify-login calls cannot both pass the check: the
    second rowcount=0 loses, exactly one request succeeds.
    """
    if accepted_counter is None:
        return False
    result = await db.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(
                User.mfa_last_used_counter.is_(None),
                User.mfa_last_used_counter < accepted_counter,
            ),
        )
        .values(mfa_last_used_counter=accepted_counter)
    )
    await db.commit()
    if result.rowcount != 1:
        logger.warning(
            "Rejected replayed or concurrent TOTP code for %s (counter=%s)",
            user.email,
            accepted_counter,
        )
        return False
    return True


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
    response: Response,
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

    # Store the secret AES-GCM-encrypted; backup codes as SHA-256 digests.
    # The secret is stored but mfa_enabled remains False until verified.
    try:
        current_user.mfa_secret = encrypt_mfa_secret(mfa_data.secret)
    except RuntimeError as exc:
        logger.error("MFA setup blocked: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MFA is unavailable: the server has no ENCRYPTION_SECRET configured.",
        )
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
    response: Response,
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

    await _upgrade_mfa_storage(db, current_user)
    secret = decrypt_mfa_secret(current_user.mfa_secret)
    accepted_counter = verify_totp_with_counter(secret, body.code)
    if not await _claim_totp_counter(db, current_user, accepted_counter):
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
    response: Response,
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

    if not current_user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA secret missing")

    await _upgrade_mfa_storage(db, current_user)
    secret = decrypt_mfa_secret(current_user.mfa_secret)

    # Verify with TOTP or backup code
    code_valid = await _claim_totp_counter(
        db, current_user, verify_totp_with_counter(secret, body.code)
    )

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
    response: Response,
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

    await _upgrade_mfa_storage(db, current_user)
    secret = current_user.mfa_secret
    if not secret or not await _claim_totp_counter(
        db,
        current_user,
        verify_totp_with_counter(decrypt_mfa_secret(secret), body.code),
    ):
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
    response: Response,
    body: MFALoginVerifyRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """
    Complete login by verifying MFA code.

    Called after initial login returns mfa_required=True.
    Accepts either TOTP code or backup code.
    The mfa_pending token travels in the request body so it never lands in
    URLs (proxy/access logs).
    """
    temp_token = body.temp_token
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

    await _upgrade_mfa_storage(db, user)

    # Try TOTP verification (rejecting replays of an already-used code)
    code_valid = await _claim_totp_counter(
        db,
        user,
        verify_totp_with_counter(decrypt_mfa_secret(user.mfa_secret), body.code),
    )

    # If TOTP fails, try backup code
    if not code_valid and user.mfa_backup_codes:
        is_backup_valid, code_index = verify_backup_code(body.code, user.mfa_backup_codes)
        if is_backup_valid and code_index is not None:
            # Remove used backup code
            codes = list(user.mfa_backup_codes)
            codes.pop(code_index)
            user.mfa_backup_codes = codes
            code_valid = True
            logger.info(f"MFA login with backup code for user {email}")

    if not code_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid verification code"
        )

    # Persist the anti-replay counter (TOTP) / consumed backup code
    await db.commit()

    # Generate full access token
    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    logger.info(f"MFA login completed for user {email}")

    # M3: server-side refresh session for the MFA login.
    refresh_token = await _issue_refresh_session(db, user, request)
    await db.commit()  # token_sessions row must survive the request

    payload = Token(access_token=access_token, token_type="bearer").model_dump()
    payload["refresh_token"] = refresh_token
    response = JSONResponse(content=payload)
    set_refresh_cookie(response, refresh_token)
    set_auth_cookie(response, access_token)
    return response
