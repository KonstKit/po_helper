from __future__ import annotations

import json
from typing import Callable, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import get_current_user
from app.core.crypto import decrypt_str
from app.main import app
from app.models import IntegrationSetting


@pytest.fixture
def override_user_dep():
    """
    Temporarily override the get_current_user dependency.

    Yields a setter that accepts a callable returning a user (or raising),
    then restores the original override after the test.
    """

    original = app.dependency_overrides.get(get_current_user)

    def apply(factory: Callable):
        app.dependency_overrides[get_current_user] = factory

    yield apply

    if original is not None:
        app.dependency_overrides[get_current_user] = original
    else:
        app.dependency_overrides.pop(get_current_user, None)


class _LimitedUser:
    id = 2
    email = "limited@example.com"
    username = "limited"
    full_name = "Limited User"
    is_active = True
    is_superuser = False
    mfa_enabled = False
    mfa_secret: Optional[str] = None
    mfa_backup_codes = None

    def has_permission(self, _permission: str) -> bool:
        return False

    def has_role(self, _role: str) -> bool:
        return False

    @property
    def mfa_configured(self) -> bool:
        return False

    @property
    def remaining_backup_codes(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_confluence_requires_auth(client, override_user_dep):
    def _raise_unauth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    override_user_dep(_raise_unauth)

    resp = await client.get("/api/v1/settings/confluence")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_confluence_requires_permission(client, override_user_dep):
    override_user_dep(lambda: _LimitedUser())

    payload = {"base_url": "https://conf.example", "api_token": "token"}
    resp = await client.put("/api/v1/settings/confluence", json=payload)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_github_requires_auth(client, override_user_dep):
    def _raise_unauth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    override_user_dep(_raise_unauth)

    resp = await client.get("/api/v1/settings/github")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_github_requires_permission(client, override_user_dep):
    override_user_dep(lambda: _LimitedUser())

    payload = {"api_token": "token", "base_url": "https://api.github.com"}
    resp = await client.put("/api/v1/settings/github", json=payload)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_github_put_masks_and_encrypts(client, db_session):
    payload = {
        "api_token": "ghp_secret_token",
        "webhook_secret": "whsec_123",
        "base_url": "https://api.github.com",
    }

    resp = await client.put("/api/v1/settings/github", json=payload)
    assert resp.status_code == 200
    body = resp.json()

    assert body["api_token"] is None
    assert body["has_token"] is True
    assert body["has_webhook_secret"] is True

    row = await db_session.execute(
        select(IntegrationSetting).where(IntegrationSetting.kind == "github")
    )
    setting = row.scalar_one()
    # Stored token is encrypted JSON bundle.
    decrypted = decrypt_str(setting.api_token)
    bundle = json.loads(decrypted)
    assert bundle["api_token"] == payload["api_token"]
    assert bundle["webhook_secret"] == payload["webhook_secret"]
