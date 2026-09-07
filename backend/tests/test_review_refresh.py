"""TEMPORARY review-verification tests (delete after review)."""

from datetime import timedelta

from app.core.security import create_access_token


async def _login(client, email="rev-user@example.com", username="revuser"):
    r = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "username": username,
            "full_name": "Rev User",
            "password": "StrongPassword123!",
        },
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
    )
    assert r.status_code == 200, r.text
    return r


async def test_refresh_cookie_only_no_body(client):
    """F2: browser has only the httpOnly refresh cookie, no JS-readable token."""
    login = await _login(client)
    print("SET-COOKIE:", login.headers.get_list("set-cookie"))
    print("CLIENT COOKIES:", dict(client.cookies))
    r = await client.post("/api/v1/auth/refresh", headers={"Origin": "http://test"})
    print("REFRESH no-body status:", r.status_code, r.text[:300])


async def test_logout_leaves_refresh_session_alive(client):
    """F1: browser logout (no body) then reuse the refresh token."""
    login = await _login(client, "rev-user2@example.com", "revuser2")
    refresh_tok = login.json()["refresh_token"]
    lo = await client.post("/api/v1/auth/logout", headers={"Origin": "http://test"})
    assert lo.status_code == 200
    print("LOGOUT set-cookie:", lo.headers.get_list("set-cookie"))
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_tok},
        headers={"Origin": "http://test"},
    )
    print("REFRESH after logout status:", r.status_code, r.text[:200])


async def test_mfa_pending_token_accepted_as_session(client):
    """Does deps accept a type=mfa_pending token as a full session?"""
    await _login(client, "rev-user3@example.com", "revuser3")
    client.cookies.clear()
    temp = create_access_token(
        data={"sub": "rev-user3@example.com", "type": "mfa_pending"},
        expires_delta=timedelta(minutes=5),
    )
    me = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {temp}"})
    print("mfa_pending as bearer ->", me.status_code, me.text[:200])
