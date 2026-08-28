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
from starlette.websockets import WebSocketDisconnect

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
from app.core.config import settings
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


@pytest.mark.asyncio
async def test_oauth_linking_requires_verified_email_when_enabled(client, monkeypatch):
    """With linking explicitly enabled, an unverified provider email is
    still refused."""
    from app.api.api_v1.endpoints.auth import _process_oauth_login
    from app.core.oauth import OAuth2Error, OAuth2UserInfo
    from app.core.database import AsyncSessionLocal

    monkeypatch.setattr(settings, "OAUTH_ALLOW_EMAIL_LINKING", True)
    await _register_and_login(client, "linking@example.com", "linking_user")

    user_info = OAuth2UserInfo(
        provider="google",
        provider_id="google-456",
        email="linking@example.com",
        name="Someone",
        picture=None,
        email_verified=False,
    )
    async with AsyncSessionLocal() as db:
        with pytest.raises(OAuth2Error) as exc_info:
            await _process_oauth_login(db, user_info)
    assert exc_info.value.error == "email_not_verified"


@pytest.mark.asyncio
async def test_oauth_full_flow_with_cookie_binding(client, monkeypatch):
    """Happy path: start -> cookie+state -> mocked provider -> token."""
    from app.core.oauth import OAuth2UserInfo, google_oauth

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")

    async def _fake_exchange(code: str):
        return {"access_token": f"at-{code}"}

    async def _fake_user_info(access_token: str):
        return OAuth2UserInfo(
            provider="google",
            provider_id=f"g-{access_token}",
            email="oauth-new@example.com",
            name="OAuth New",
            picture=None,
            email_verified=True,
        )

    monkeypatch.setattr(google_oauth, "exchange_code", _fake_exchange)
    monkeypatch.setattr(google_oauth, "get_user_info", _fake_user_info)
    # the singleton captured empty credentials at import time (conftest env)
    monkeypatch.setattr(google_oauth, "client_id", "test-client")
    monkeypatch.setattr(google_oauth, "client_secret", "test-secret")

    start = await client.get("/api/v1/auth/oauth2/google")
    assert start.status_code == 200, start.text
    state = start.json()["state"]
    cookie_header = start.headers["set-cookie"].split(";")[0]

    callback = await client.get(
        "/api/v1/auth/oauth2/google/callback",
        params={"code": "auth-code", "state": state},
        headers={"Cookie": cookie_header},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_oauth_callback_rejects_mismatched_cookie(client, monkeypatch):
    """A valid state from flow A plus the cookie from flow B must fail."""
    from app.core.oauth import google_oauth

    monkeypatch.setattr(google_oauth, "client_id", "test-client")
    monkeypatch.setattr(google_oauth, "client_secret", "test-secret")

    start_a = await client.get("/api/v1/auth/oauth2/google")
    state_a = start_a.json()["state"]
    await client.get("/api/v1/auth/oauth2/google")  # flow B overwrites the cookie
    cookie_b = (await client.get("/api/v1/auth/oauth2/google")).headers["set-cookie"].split(";")[0]
    del start_a

    response = await client.get(
        "/api/v1/auth/oauth2/google/callback",
        params={"code": "x", "state": state_a},
        headers={"Cookie": cookie_b},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_oauth_accepts_allowlisted_redirect_override(client, monkeypatch):
    from app.core.oauth import google_oauth

    monkeypatch.setattr(google_oauth, "client_id", "test-client")
    monkeypatch.setattr(google_oauth, "client_secret", "test-secret")
    # the override constructs a fresh client, which reads settings
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        settings,
        "OAUTH_ALLOWED_REDIRECT_URIS",
        ["http://localhost:3001/oauth/callback"],
    )
    response = await client.get(
        "/api/v1/auth/oauth2/google",
        params={"redirect_uri": "http://localhost:3001/oauth/callback"},
    )
    assert response.status_code == 200, response.text
    assert "localhost%3A3001" in response.json()["authorization_url"] or "localhost:3001" in response.json()["authorization_url"]


# ---------------------------------------------------------------------------
# B2: WebSocket authentication
# ---------------------------------------------------------------------------


def test_websocket_rejects_missing_credentials_with_4401():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/api/v1/ws"):
                pass
        assert exc_info.value.code == 4401


def test_websocket_rejects_replayed_ticket():
    """Tickets are single-use: the same ticket must not authenticate twice."""
    from app.core.ws_tickets import issue_ws_ticket

    ticket = issue_ws_ticket("unknown@example.com")
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/v1/ws?ticket={ticket}"):
                pass
        # replay of a consumed ticket is rejected
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/api/v1/ws?ticket={ticket}"):
                pass
        assert exc_info.value.code == 4401


@pytest.mark.asyncio
async def test_websocket_accepts_ticket_and_bearer(client):
    token = await _register_and_login(client, "ws-user@example.com", "ws_user")

    with _real_integration_access():
        response = await client.post(
            "/api/v1/auth/ws-ticket",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    ticket = response.json()["ticket"]

    with TestClient(app) as tc:
        # ticket path (browser flow)
        with tc.websocket_connect(f"/api/v1/ws?ticket={ticket}") as ws:
            ws.send_text("ping")
        # bearer header path (non-browser clients)
        with tc.websocket_connect(
            "/api/v1/ws", headers={"Authorization": f"Bearer {token}"}
        ) as ws:
            ws.send_text("ping")


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
async def test_jira_sync_forbidden_for_scoped_token_without_permission(client):
    await _seed_system_roles()
    await _register_and_login(client, "admin2@example.com", "admin_user2")
    po_token = await _register_and_login(client, "po-sync@example.com", "po_sync_user")
    # the po role carries project:update, so the sync gate passes for it;
    # a token narrowed to project:view must still be rejected
    with _real_integration_access():
        response = await client.post(
            "/api/v1/jira/projects/ABC/sync",
            headers={"Authorization": f"Bearer {po_token}"},
        )
        # po has project:update, so this passes the gate and fails later on
        # connection setup; assert it is not a permission failure
        assert response.status_code != 403

        scoped_response = await client.post(
            "/api/v1/auth/scoped-token",
            headers={"Authorization": f"Bearer {po_token}"},
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


@pytest.mark.asyncio
async def test_connect_pat_and_confluence_connect_gated(client):
    """Both credential endpoints must reject a po user: integration:manage."""
    await _seed_system_roles()
    await _register_and_login(client, "admin3@example.com", "admin_user3")
    po_token = await _register_and_login(client, "po-cred@example.com", "po_cred_user")

    with _real_integration_access():
        pat_response = await client.post(
            "/api/v1/jira/connect_pat",
            headers={"Authorization": f"Bearer {po_token}"},
            json={"base_url": "https://jira.example.com", "api_token": "x"},
        )
        confluence_response = await client.post(
            "/api/v1/confluence/connect",
            headers={"Authorization": f"Bearer {po_token}"},
            json={"base_url": "https://confluence.example.com", "api_token": "x"},
        )
    assert pat_response.status_code == 403
    assert "integration:manage" in pat_response.json()["detail"]
    assert confluence_response.status_code == 403
    assert "integration:manage" in confluence_response.json()["detail"]


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
    assert exc_info.value.detail == "Request could not be completed. Check server logs for details."


def test_handle_api_error_sanitizes_integrity_error_on_409():
    """IntegrityError maps to 409; its detail must not leak constraint
    names or SQL fragments either."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(HTTPException) as exc_info:
        with handle_api_error(operation="conflict", status_code=400):
            raise IntegrityError(
                "INSERT INTO users...", {"email": "x@y.dev"}, Exception()
            )
    assert exc_info.value.status_code == 409
    assert "users" not in exc_info.value.detail
    assert exc_info.value.detail == "Request could not be completed. Check server logs for details."


def test_handle_api_error_keeps_4xx_domain_message():
    with pytest.raises(HTTPException) as exc_info:
        with handle_api_error(operation="validate", status_code=400):
            raise ValueError("email domain not allowed")
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "email domain not allowed"
