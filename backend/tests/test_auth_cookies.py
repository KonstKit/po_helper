"""Auth-cookie migration M1: login/mfa/oauth issue an httpOnly cookie,"""
"""get_current_user accepts it, logout clears it. Dual mode: the body"""
"""token keeps working for pre-M2 clients."""

import pytest

from app.core.config import settings
from app.main import app


async def _register_and_login(client, email="cookie-user@example.com"):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": "cookieuser",
            "full_name": "Cookie User",
            "password": "StrongPassword123!",
        },
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
    )
    assert response.status_code == 200, response.text
    return response


async def _clear_client_cookies(client):
    client.cookies.clear()


async def test_login_sets_httponly_cookie(client):
    response = await _register_and_login(client)
    set_cookie = response.headers.get("set-cookie", "")
    cookie_name = settings.AUTH_COOKIE_NAME
    assert cookie_name + "=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert settings.AUTH_COOKIE_SAMESITE.lower() in set_cookie.lower()
    # dual mode: the body token is still returned for pre-M2 clients
    assert response.json()["access_token"]


async def test_users_me_via_cookie_without_bearer(client, monkeypatch):
    monkeypatch.setattr(settings, 'AUTH_COOKIE_FALLBACK_ENABLED', True)
    response = await _register_and_login(client)
    body_token = response.json()["access_token"]
    assert client.cookies.get(settings.AUTH_COOKIE_NAME), "login must set the cookie"
    headers = {"Authorization": "Bearer " + body_token}
    me = await client.get("/api/v1/users/me", headers={k: v for k, v in headers.items() if False})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "cookie-user@example.com"


async def test_cookie_fallback_enabled_for_m2_session(client):
    await _register_and_login(client)
    # M2 shipped: the browser session uses the httpOnly cookie, so the
    # fallback is on by default (the frontend logout calls /auth/logout).
    assert settings.AUTH_COOKIE_FALLBACK_ENABLED is True
    me = await client.get('/api/v1/users/me')
    assert me.status_code == 200, me.text

async def test_logout_clears_cookie_and_session(client):
    await _register_and_login(client)
    assert client.cookies.get(settings.AUTH_COOKIE_NAME)
    response = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://test"},
    )
    assert response.status_code == 200, response.text
    cleared = response.headers.get("set-cookie", "").lower()
    assert settings.AUTH_COOKIE_NAME in cleared
    assert "max-age=0" in cleared or "expires= thu, 01 jan 1970" in cleared
    me = await client.get("/api/v1/users/me")
    assert me.status_code == 401, me.text


async def test_cookie_mutations_reject_cross_site_origin(client):
    await _register_and_login(client)
    # A cross-site Origin while carrying the auth cookie: CSRF blocked.
    response = await client.post(
        '/api/v1/auth/logout',
        headers={'Origin': 'https://evil.example.com'},
    )
    assert response.status_code == 403, response.text


async def test_cookie_mutations_accept_same_origin(client):
    await _register_and_login(client)
    response = await client.post(
        '/api/v1/auth/logout',
        headers={'Origin': 'http://test'},
    )
    assert response.status_code == 200, response.text


async def test_cookie_post_without_origin_is_allowed_under_strict_samesite(client):
    # SameSite=strict (default) already blocks cross-site sends; a
    # cookie request without Origin is a non-browser client.
    await _register_and_login(client)
    response = await client.post('/api/v1/auth/logout')
    assert response.status_code == 200, response.text


async def test_cookie_post_from_vite_dev_origin_is_accepted(client):
    # The default CORS allowlist must include the Vite dev server port.
    await _register_and_login(client)
    response = await client.post(
        '/api/v1/auth/logout',
        headers={'Origin': 'http://localhost:3001'},
    )
    assert response.status_code == 200, response.text

async def test_cookie_post_with_referer_origin_is_accepted(client):
    await _register_and_login(client)
    response = await client.post(
        '/api/v1/auth/logout',
        headers={'Referer': 'http://test/projects?x=1'},
    )
    assert response.status_code == 200, response.text


async def test_bearer_post_without_origin_still_works(client):
    # Non-browser API clients authenticate by header and carry no cookie;
    # the CSRF guard only inspects requests that present the cookie.
    response = await _register_and_login(client)
    body_token = response.json()['access_token']
    client.cookies.clear()
    response = await client.post(
        '/api/v1/auth/ws-ticket',
        headers={'Authorization': 'Bearer ' + body_token},
    )
    assert response.status_code == 200, response.text

async def test_login_csrf_rejects_cross_site_origin_without_cookies(client):
    # Login CSRF (M1): a cross-site form POST must not silently sign the
    'victim into an attacker account, even cookie-less.'
    response = await client.post(
        '/api/v1/auth/login',
        data={'username': 'cookie-user@example.com', 'password': 'StrongPassword123!'},
        headers={'Origin': 'https://evil.example.com'},
    )
    assert response.status_code == 403, response.text


async def test_login_without_origin_is_a_non_browser_client(client):
    response = await client.post(
        '/api/v1/auth/login',
        data={'username': 'nobody@example.com', 'password': 'Whatever123!'},
    )
    # non-browser clients have no CSRF vector; auth result is untouched
    assert response.status_code in (200, 401), response.text

async def test_bearer_header_still_works_dual_mode(client):
    response = await _register_and_login(client)
    body_token = response.json()["access_token"]
    await _clear_client_cookies(client)
    me = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer " + body_token})
    assert me.status_code == 200, me.text
