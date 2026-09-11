'''Regression tests for the JWT sid claim (DEFERRED 1.1) and
token_sessions pruning (DEFERRED 1.4).

An access token bound to a token_sessions row via the sid claim must
die the moment the session is revoked (logout, explicit revoke,
rotation) instead of staying valid until TTL expiry.'''
import pytest

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.token_session import TokenSession

async def _register_and_login(client, email='sid-user@example.com'):
    response = await client.post(
        '/api/v1/auth/register',
        json={
            'email': email,
            'username': 'siduser',
            'full_name': 'Sid User',
            'password': 'StrongPassword123!',
        },
    )
    assert response.status_code == 200, response.text
    return await client.post(
        '/api/v1/auth/login',
        data={'username': email, 'password': 'StrongPassword123!'},
        headers={'Origin': 'http://test'},
    )


async def _revoke_all_sessions(client):
    listing = await client.get('/api/v1/auth/sessions')
    assert listing.status_code == 200, listing.text
    for item in listing.json()['sessions']:
        response = await client.delete('/api/v1/auth/sessions/' + str(item['id']))
        assert response.status_code in (200, 204), response.text


@pytest.mark.asyncio
async def test_session_revocation_kills_access_cookie_immediately(client):
    '''REVOCATION 1.1: the access cookie must stop working right away.'''
    await _register_and_login(client)
    me = await client.get('/api/v1/users/me')
    assert me.status_code == 200, me.text
    await _revoke_all_sessions(client)
    me = await client.get('/api/v1/users/me')
    assert me.status_code == 401, me.text


@pytest.mark.asyncio
async def test_rotation_invalidates_previous_access_cookie(client):
    '''After refresh rotation the OLD access cookie is dead (new sid).'''
    await _register_and_login(client)
    old_access = client.cookies.get(settings.AUTH_COOKIE_NAME)
    assert old_access
    refreshed = await client.post(
        '/api/v1/auth/refresh', headers={'Origin': 'http://test'},
    )
    assert refreshed.status_code == 200, refreshed.text
    client.cookies.set(settings.AUTH_COOKIE_NAME, old_access)
    me = await client.get('/api/v1/users/me')
    assert me.status_code == 401, me.text


@pytest.mark.asyncio
async def test_scoped_token_without_sid_still_works(client):
    '''Machine clients use scoped tokens (no sid) - unaffected.'''
    await _register_and_login(client)
    me = await client.get('/api/v1/users/me')
    assert me.status_code == 200, me.text
    from datetime import timedelta

    from app.core.security import create_access_token

    # crafted machine token: scopes, no sid (the scoped-token endpoint
    # resolves current_user through the fixture override in tests)
    scoped = create_access_token(
        data={'sub': 'sid-user@example.com', 'scopes': ['project:view']},
        expires_delta=timedelta(minutes=5),
    )
    client.cookies.clear()
    who = await client.get(
        '/api/v1/users/me',
        headers={'Authorization': 'Bearer ' + scoped},
    )
    assert who.status_code == 200, who.text


@pytest.mark.asyncio
async def test_prune_token_sessions_removes_only_dead_rows(db_session):
    '''DEFERRED 1.4: expired and stale-revoked rows are deleted.'''
    from app.services.token_session_maintenance import prune_token_sessions

    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            TokenSession(
                user_id=1,
                refresh_token_hash='expired',
                expires_at=now - timedelta(days=1),
            ),
            TokenSession(
                user_id=1,
                refresh_token_hash='stale-revoked',
                expires_at=now + timedelta(days=10),
                revoked_at=now - timedelta(days=8),
            ),
            TokenSession(
                user_id=1,
                refresh_token_hash='live',
                expires_at=now + timedelta(days=10),
            ),
            TokenSession(
                user_id=1,
                refresh_token_hash='fresh-revoked',
                expires_at=now + timedelta(days=10),
                revoked_at=now - timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()
    deleted = await prune_token_sessions(
        db_session,
        revoked_before=now - timedelta(days=7),
        expired_before=now,
    )
    assert deleted == 2
    remaining = {
        row.refresh_token_hash
        for row in (await db_session.execute(__import__('sqlalchemy').select(TokenSession))).scalars()
    }
    assert sorted(remaining) == ['fresh-revoked', 'live']
