"""JWT storage M4 contract: session issuance bodies carry no tokens.

The default configuration serves the browser session exclusively
through the httpOnly auth/refresh cookies. AUTH_BODY_TOKENS_ENABLED=true
(set for the bulk of the suite in conftest) restores the dual-mode body
payload as a deployment rollback; these tests pin the M4 default."""

import pytest

from app.core.config import settings


async def _register_and_login_m4(client, email="m4-user@example.com"):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": "m4user",
            "full_name": "M4 User",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 200, response.text
    return await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
        headers={"Origin": "http://test"},
    )


@pytest.fixture
def m4_mode(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_BODY_TOKENS_ENABLED", False)


async def test_login_body_has_no_tokens(m4_mode, client):
    response = await _register_and_login_m4(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.AUTH_COOKIE_NAME + "=" in set_cookie
    assert "refresh_token=" in set_cookie


async def test_login_cookie_session_works_without_body_tokens(m4_mode, client):
    await _register_and_login_m4(client)
    me = await client.get("/api/v1/users/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "m4-user@example.com"


async def test_refresh_cookie_only_body_has_no_tokens(m4_mode, client):
    await _register_and_login_m4(client)
    old_refresh = client.cookies.get("refresh_token")
    assert old_refresh
    response = await client.post(
        "/api/v1/auth/refresh", headers={"Origin": "http://test"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    # rotation: the presented token must no longer authenticate
    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
        headers={"Origin": "http://test"},
    )
    assert replay.status_code == 401, replay.text


async def test_logout_still_revokes_in_m4_mode(m4_mode, client):
    await _register_and_login_m4(client)
    old_refresh = client.cookies.get("refresh_token")
    response = await client.post(
        "/api/v1/auth/logout", headers={"Origin": "http://test"}
    )
    assert response.status_code == 200, response.text
    replay = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": old_refresh},
        headers={"Origin": "http://test"},
    )
    assert replay.status_code == 401, replay.text
