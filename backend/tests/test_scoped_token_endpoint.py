from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.api_v1.endpoints.auth import issue_scoped_token
from app.core.config import settings
from app.schemas.user import ScopedTokenRequest


def _fake_user(*, is_active: bool):
    return SimpleNamespace(
        is_active=is_active,
        email="user@example.com",
        roles=[],
        has_permission=lambda _perm: False,
    )


@pytest.mark.asyncio
async def test_issue_scoped_token_rejects_inactive_user():
    payload = ScopedTokenRequest(scopes=["project:view"], expires_minutes=1)

    with pytest.raises(HTTPException) as exc_info:
        await issue_scoped_token(payload, current_user=_fake_user(is_active=False))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Inactive user"


@pytest.mark.asyncio
async def test_issue_scoped_token_rejects_ttl_above_default_access_ttl():
    payload = ScopedTokenRequest(
        scopes=["project:view"],
        expires_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES + 1,
    )

    with pytest.raises(HTTPException) as exc_info:
        await issue_scoped_token(payload, current_user=_fake_user(is_active=True))

    assert exc_info.value.status_code == 400
    assert "cannot exceed" in str(exc_info.value.detail)
