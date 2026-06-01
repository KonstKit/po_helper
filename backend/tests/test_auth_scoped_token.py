from __future__ import annotations

from typing import Callable, Optional, Set

import pytest

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import decode_token
from app.main import app
from app.models import Permissions, Project


@pytest.fixture
def override_user_dep():
    original = app.dependency_overrides.get(get_current_user)

    def apply(factory: Callable):
        app.dependency_overrides[get_current_user] = factory

    yield apply

    if original is not None:
        app.dependency_overrides[get_current_user] = original
    else:
        app.dependency_overrides.pop(get_current_user, None)


class _AuthUser:
    def __init__(self, *, is_active: bool, permissions: Set[str]) -> None:
        self.id = 42
        self.email = "scoped@example.com"
        self.username = "scoped"
        self.full_name = "Scoped User"
        self.is_active = is_active
        self.is_superuser = False
        self._permissions = permissions
        self.roles = []
        self.mfa_enabled = False
        self.mfa_secret: Optional[str] = None
        self.mfa_backup_codes = None

    def has_permission(self, permission: str) -> bool:
        return permission in self._permissions

    def has_role(self, _role: str) -> bool:
        return False

    @property
    def mfa_configured(self) -> bool:
        return False

    @property
    def remaining_backup_codes(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_scoped_token_rejects_inactive_user(client, override_user_dep):
    override_user_dep(lambda: _AuthUser(is_active=False, permissions={Permissions.ADMIN}))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": 10},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"


@pytest.mark.asyncio
async def test_scoped_token_rejects_ttl_above_access_token_limit(client, override_user_dep):
    override_user_dep(lambda: _AuthUser(is_active=True, permissions={Permissions.ADMIN}))
    too_large_ttl = int(settings.ACCESS_TOKEN_EXPIRE_MINUTES) + 1

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": too_large_ttl},
    )

    assert response.status_code == 400
    assert "cannot exceed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scoped_token_allows_non_admin_with_accessible_tenant(
    client, db_session, override_user_dep
):
    user = _AuthUser(is_active=True, permissions={Permissions.PROJECT_VIEW})
    override_user_dep(lambda: user)

    db_session.add(
        Project(
            jira_key="SCOPED-TEN-1",
            name="Scoped Tenant Access",
            owner_id=user.id,
            meta={"tenant_id": "tenant-a"},
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={
            "scopes": [Permissions.PROJECT_VIEW],
            "expires_minutes": 10,
            "tenant_id": "tenant-a",
        },
    )

    assert response.status_code == 200, response.text
    payload = decode_token(response.json()["access_token"])
    assert payload["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_scoped_token_rejects_non_admin_with_inaccessible_tenant(
    client, db_session, override_user_dep
):
    user = _AuthUser(is_active=True, permissions={Permissions.PROJECT_VIEW})
    override_user_dep(lambda: user)

    db_session.add(
        Project(
            jira_key="SCOPED-TEN-2",
            name="Other Tenant",
            owner_id=999,
            meta={"tenant_id": "tenant-b", "member_ids": [999]},
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={
            "scopes": [Permissions.PROJECT_VIEW],
            "expires_minutes": 10,
            "tenant_id": "tenant-a",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Requested tenant_id is not accessible for current user"


@pytest.mark.asyncio
async def test_scoped_token_rejects_too_many_scopes(client, override_user_dep):
    override_user_dep(lambda: _AuthUser(is_active=True, permissions={Permissions.ADMIN}))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW] * 33, "expires_minutes": 10},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scoped_token_rejects_scope_too_long(client, override_user_dep):
    override_user_dep(lambda: _AuthUser(is_active=True, permissions={Permissions.ADMIN}))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": ["x" * 65], "expires_minutes": 10},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_scoped_token_rejects_tenant_id_too_long(client, override_user_dep):
    override_user_dep(lambda: _AuthUser(is_active=True, permissions={Permissions.ADMIN}))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={
            "scopes": [Permissions.PROJECT_VIEW],
            "expires_minutes": 10,
            "tenant_id": "t" * 129,
        },
    )

    assert response.status_code == 422
