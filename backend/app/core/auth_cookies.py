#!/usr/bin/env python3
"""httpOnly auth-cookie helpers (JWT storage migration M1).

The cookie carries the same access JWT that the body used to carry
exclusively. Dual mode (RFC M1): the body token is still returned so
pre-M2 clients keep working; the browser session relies on the cookie
from M2 on. Server-side revocation arrives with M3 (token_sessions)."""

from typing import Literal, cast

from fastapi import Request, Response, WebSocket

from app.core.config import settings


def _cookie_max_age() -> int:
    return int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) * 60


def set_auth_cookie(response: Response, token: str) -> None:
    """Attach the access JWT as an httpOnly session cookie."""
    if not settings.AUTH_COOKIE_ENABLED:
        return
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=token,
        max_age=_cookie_max_age(),
        expires=_cookie_max_age(),
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", settings.AUTH_COOKIE_SAMESITE),
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the auth cookie (logout; M3 adds server-side revocation)."""
    if not settings.AUTH_COOKIE_ENABLED:
        return
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", settings.AUTH_COOKIE_SAMESITE),
    )


def get_auth_cookie_token(request: "Request | WebSocket") -> str | None:
    """Read the access JWT from the request cookie jar, if present."""
    if not settings.AUTH_COOKIE_ENABLED:
        return None
    return request.cookies.get(settings.AUTH_COOKIE_NAME)


REFRESH_COOKIE_NAME = "refresh_token"
# /auth scope (not just /refresh) so logout receives the cookie and
# can revoke the presented session without a JS-readable token.
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an httpOnly cookie scoped to refresh."""
    if not settings.AUTH_COOKIE_ENABLED:
        return
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=int(settings.REFRESH_TOKEN_EXPIRE_DAYS) * 86400,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", settings.AUTH_COOKIE_SAMESITE),
    )


def clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh cookie (logout)."""
    if not settings.AUTH_COOKIE_ENABLED:
        return
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=cast("Literal['lax', 'strict', 'none']", settings.AUTH_COOKIE_SAMESITE),
    )


def get_refresh_cookie_token(request) -> str | None:
    """Read the refresh token from the request cookie jar."""
    if not settings.AUTH_COOKIE_ENABLED:
        return None
    return request.cookies.get(REFRESH_COOKIE_NAME)
