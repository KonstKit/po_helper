"""Regression tests for the Blocker findings of the staff code review.

Covers:
- B1: OAuth signed-state validation, redirect_uri allow list, callback
  cookie binding, email-linking policy.
- B2: WebSocket /ws rejects unauthenticated handshakes.
- B3: Mutating integration endpoints enforce RBAC permissions.
- B4: 5xx responses do not leak internal exception details.
- B5: rate-limited endpoints return slowapi headers (the missing
  ``response`` parameter used to 500 after a successful commit).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.testclient import TestClient

from app.api.deps import (
    get_current_user as _get_current_user,
    require_integration_access as _require_integration_access,
)
from app.core.database import AsyncSessionLocal
from app.core.oauth_state import (
    OAuthStateError,
    create_oauth_state,
    verify_oauth_state,
)
from app.core.rate_limit import limiter
from app.main import app
from app.models import Role, SYSTEM_ROLES
from app.utils.error_handling import handle_api_error


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    limiter.reset()
    yield
    limiter.reset()


async def _seed_system_roles():
    """The test app never runs its lifespan, so system RBAC roles must be
    created explicitly for role-dependent assertions."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for name, config in SYSTEM_ROLES.items():
                existing = (
                    await db.execute(select(Role).where(Role.name == name))
                ).scalar_one_or_none()
                if existing is None:
                    db.add(
                        Role(
                            name=name,
                            display_name=config["display_name"],
                            description=config["description"],
                            is_system=True,
                            permissions=config["permissions"],
                        )
                    )


@contextmanager
def _real_integration_access():
    """conftest replaces auth dependencies with a dummy superuser; permission
    gates must be tested against the real dependency chain."""
    saved_integration = app.dependency_overrides.pop(_require_integration_access, None)
    saved_current = app.dependency_overrides.pop(_get_current_user, None)
    try:
        yield
    finally:
        if saved_integration is not None:
            app.dependency_overrides[_require_integration_access] = saved_integration
        if saved_current is not None:
            app.dependency_overrides[_get_current_user] = saved_current


async def _register_and_login(client, email: str, username: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": username,
            "full_name": username.title(),
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# ---------------------------------------------------------------------------
# B5: slowapi headers regression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_returns_rate_limit_headers(client, monkeypatch):
    """slowapi's _inject_headers requires a Response parameter; without it
    register 500s after committing the user (regression)."""
    # conftest disables the limiter globally for tests; this regression is
    # about the enabled path, so re-enable it for this test only.
    monkeypatch.setattr(limiter, "enabled", True)
    monkeypatch.setattr(limiter, "_headers_enabled", True)
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "ratelimit-regression@example.com",
            "username": "ratelimit-regression",
            "full_name": "Rate Limit",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 200, response.text
    assert "X-RateLimit-Remaining" in response.headers
    assert response.json()["email"] == "ratelimit-regression@example.com"


# ---------------------------------------------------------------------------
# B1: OAuth state security
# ---------------------------------------------------------------------------


def test_oauth_state_roundtrip_and_provider_binding():
    state = create_oauth_state("google", redirect_uri=None)
    payload = verify_oauth_state(state, provider="google")
    assert payload["provider"] == "google"
    assert payload["redirect_uri"] is None

    with pytest.raises(OAuthStateError):
        verify_oauth_state(state, provider="microsoft")


def test_oauth_state_tamper_and_expiry():
    state = create_oauth_state("google")
    with pytest.raises(OAuthStateError):
        verify_oauth_state(state[:-2] + "zz", provider="google")

    expired = create_oauth_state("google", max_age=-1)
    with pytest.raises(OAuthStateError):
        verify_oauth_state(expired, provider="google")


@pytest.mark.asyncio
async def test_oauth_start_rejects_redirect_uri_outside_allow_list(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.OAUTH_ALLOWED_REDIRECT_URIS",
        ["https://app.example.com/oauth/callback"],
    )
    response = await client.get(
        "/api/v1/auth/oauth2/google",
        params={"redirect_uri": "https://evil.example.com/callback"},
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_oauth_callback_rejects_forged_state(client):
    response = await client.get(
        "/api/v1/auth/oauth2/google/callback",
        params={"code": "anything", "state": "forged-state-value"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "OAuth2 state validation failed"


@pytest.mark.asyncio
async def test_oauth_callback_rejects_signed_state_without_cookie(client):
    """A signed state from another browser (no binding cookie) must fail."""
    state = create_oauth_state("google")
    response = await client.get(
        "/api/v1/auth/oauth2/google/callback",
        params={"code": "anything", "state": state},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_oauth_login_refuses_email_linking_by_default(client):
    """OAuth login with an existing password-account email must not link
    silently when OAUTH_ALLOW_EMAIL_LINKING is disabled."""
    from app.api.api_v1.endpoints.auth import _process_oauth_login
    from app.core.oauth import OAuth2UserInfo
    from app.core.database import AsyncSessionLocal

    await _register_and_login(
        client, "existing@example.com", "existing_user"
    )

    user_info = OAuth2UserInfo(
        provider="google",
        provider_id="google-123",
        email="existing@example.com",
        name="Attacker",
        picture=None,
        email_verified=True,
    )
    from app.core.oauth import OAuth2Error

    async with AsyncSessionLocal() as db:
        with pytest.raises(OAuth2Error) as exc_info:
            await _process_oauth_login(db, user_info)
    assert exc_info.value.error == "email_linking_disabled"


# ---------------------------------------------------------------------------
# B2: WebSocket authentication
# ---------------------------------------------------------------------------


def test_websocket_rejects_missing_token():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws"):
                pass


def test_websocket_rejects_invalid_token():
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/v1/ws?token=not-a-jwt"):
                pass


# ---------------------------------------------------------------------------
# B3: integration permission gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jira_connect_forbidden_without_integration_manage(client):
    """First user becomes admin; the second gets the 'po' role, which must
    not be allowed to overwrite Jira credentials."""
    await _seed_system_roles()
    await _register_and_login(client, "admin@example.com", "admin_user")
    po_token = await _register_and_login(client, "po@example.com", "po_user")

    with _real_integration_access():
        response = await client.post(
            "/api/v1/jira/connect",
            headers={"Authorization": f"Bearer {po_token}"},
            json={"base_url": "https://jira.example.com", "api_token": "x"},
        )
    assert response.status_code == 403
    assert "integration:manage" in response.json()["detail"]


@pytest.mark.asyncio
async def test_jira_sync_forbidden_for_readonly_user(client):
    await _seed_system_roles()
    await _register_and_login(client, "admin2@example.com", "admin_user2")
    viewer_token = await _register_and_login(client, "viewer@example.com", "viewer_user")
    # second registered user gets 'po'; verify sync needs project:update and
    # a token without any roles fails closed
    with _real_integration_access():
        response = await client.post(
            "/api/v1/jira/projects/ABC/sync",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        # po has project:update, so this passes the gate and fails later on
        # connection setup; assert it is not a permission failure
        assert response.status_code != 403

        scoped_response = await client.post(
            "/api/v1/auth/scoped-token",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"scopes": ["project:view"], "expires_minutes": 15},
        )
    assert scoped_response.status_code == 200, scoped_response.text
    scoped = scoped_response.json()["access_token"]
    with _real_integration_access():
        response = await client.post(
            "/api/v1/jira/projects/ABC/sync",
            headers={"Authorization": f"Bearer {scoped}"},
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# B4: internal error details
# ---------------------------------------------------------------------------


def test_handle_api_error_hides_5xx_details():
    with pytest.raises(HTTPException) as exc_info:
        with handle_api_error(operation="boom", status_code=500):
            raise SQLAlchemyError(
                "(sqlite3.OperationalError) no such table: secret_table"
            )
    assert exc_info.value.status_code == 500
    assert "sqlite3" not in exc_info.value.detail
    assert exc_info.value.detail == "Internal server error. Check server logs for details."


def test_handle_api_error_keeps_4xx_domain_message():
    with pytest.raises(HTTPException) as exc_info:
        with handle_api_error(operation="validate", status_code=400):
            raise ValueError("email domain not allowed")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "email domain not allowed"
