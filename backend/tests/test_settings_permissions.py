from __future__ import annotations

import json
from typing import Callable, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import get_current_user
from app.core.request_context import set_token_scopes, set_token_tenant_id
from app.core.crypto import decrypt_str
from app.core.security import decode_token
from app.main import app
from app.models import IntegrationSetting, Permissions, Project


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


class _PermissionUser(_LimitedUser):
    def __init__(
        self,
        *,
        user_id: int,
        permissions: set[str],
        is_active: bool = True,
        is_superuser: bool = False,
    ) -> None:
        self.id = user_id
        self.email = f"user{user_id}@example.com"
        self.username = f"user{user_id}"
        self.full_name = f"User {user_id}"
        self.is_active = is_active
        self.is_superuser = is_superuser
        self._permissions = permissions

    def has_permission(self, permission: str) -> bool:
        return self.is_superuser or permission in self._permissions


def _user_dep(
    user: _PermissionUser,
    tenant_id: Optional[str] = None,
    token_scopes: Optional[list[str]] = None,
):
    async def _factory():
        set_token_scopes(tuple(token_scopes) if token_scopes is not None else None)
        set_token_tenant_id(tenant_id)
        return user

    return _factory


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


@pytest.mark.parametrize("provider", ["gitlab", "testrail", "bitbucket"])
@pytest.mark.asyncio
async def test_optional_integration_get_requires_auth(client, override_user_dep, provider):
    """GitLab/TestRail/Bitbucket settings must require auth, like Jira/Confluence/GitHub.

    Regression: these get/put/test endpoints previously declared only
    ``Depends(get_db)`` with no ``current_user``, so an unauthenticated caller
    could read/overwrite integration credentials and trigger ``/test`` (which
    decrypts the stored token and issues a request to an arbitrary base_url —
    secret-use leak + SSRF).
    """
    def _raise_unauth():
        raise HTTPException(status_code=401, detail="Not authenticated")

    override_user_dep(_raise_unauth)
    resp = await client.get(f"/api/v1/settings/{provider}")
    assert resp.status_code == 401


@pytest.mark.parametrize("provider", ["gitlab", "testrail", "bitbucket"])
@pytest.mark.asyncio
async def test_optional_integration_put_requires_permission(client, override_user_dep, provider):
    """A user without SETTINGS_UPDATE cannot overwrite GitLab/TestRail/Bitbucket creds."""
    override_user_dep(lambda: _LimitedUser())
    resp = await client.put(
        f"/api/v1/settings/{provider}",
        json={"base_url": "https://attacker.example", "api_token": "token"},
    )
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


@pytest.mark.asyncio
async def test_scoped_token_rejects_inactive_user(client, override_user_dep):
    user = _PermissionUser(user_id=20, permissions={Permissions.ADMIN}, is_active=False)
    override_user_dep(_user_dep(user, tenant_id="tenant-a"))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [], "expires_minutes": 5, "tenant_id": "tenant-a"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Inactive user"


@pytest.mark.asyncio
async def test_scoped_token_rejects_ttl_above_access_policy(
    client, override_user_dep, monkeypatch
):
    from app.api.api_v1.endpoints.auth import settings as auth_settings

    user = _PermissionUser(user_id=21, permissions={Permissions.ADMIN}, is_active=True)
    override_user_dep(_user_dep(user, tenant_id="tenant-a"))
    monkeypatch.setattr(auth_settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 10)

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [], "expires_minutes": 11, "tenant_id": "tenant-a"},
    )
    assert response.status_code == 400
    assert "cannot exceed 10" in response.json()["detail"]


@pytest.mark.asyncio
async def test_scoped_token_cannot_escalate_beyond_caller_scopes(client, override_user_dep):
    user = _PermissionUser(
        user_id=22,
        permissions={Permissions.PROJECT_VIEW, Permissions.PROJECT_CREATE},
        is_active=True,
    )
    override_user_dep(
        _user_dep(
            user,
            tenant_id=None,
            token_scopes=[Permissions.PROJECT_VIEW],
        )
    )

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_CREATE], "expires_minutes": 5},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Requested scopes exceed your effective permissions"


@pytest.mark.asyncio
async def test_scoped_token_rejects_tenant_mismatch_with_caller_token(
    client, override_user_dep
):
    user = _PermissionUser(user_id=23, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(user, tenant_id="tenant-a", token_scopes=[Permissions.PROJECT_VIEW]))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": 5, "tenant_id": "tenant-b"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Requested tenant_id does not match caller token tenant"


@pytest.mark.asyncio
async def test_scoped_token_rejects_arbitrary_tenant_for_non_admin_without_tenant_token(
    client, override_user_dep
):
    user = _PermissionUser(user_id=24, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(user, tenant_id=None, token_scopes=[Permissions.PROJECT_VIEW]))

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": 5, "tenant_id": "tenant-a"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Requested tenant_id is not accessible for current user"


@pytest.mark.asyncio
async def test_scoped_token_allows_member_accessible_tenant(
    client, db_session, override_user_dep
):
    user = _PermissionUser(user_id=25, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(user, tenant_id=None, token_scopes=[Permissions.PROJECT_VIEW]))

    tenant_project = Project(
        jira_key="TEN-A-MEMBER-TOKEN",
        name="Tenant Member Token",
        owner_id=999,
        meta={"tenant_id": "tenant-a", "member_ids": [user.id]},
    )
    db_session.add(tenant_project)
    await db_session.commit()

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": 5, "tenant_id": "tenant-a"},
    )

    assert response.status_code == 200, response.text
    payload = decode_token(response.json()["access_token"])
    assert payload["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_projects_list_filters_by_tenant_and_membership(client, db_session, override_user_dep):
    viewer = _PermissionUser(user_id=30, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(viewer, tenant_id="tenant-a"))

    p_owned = Project(jira_key="TEN-A-OWN", name="Owned", owner_id=viewer.id, meta={"tenant_id": "tenant-a"})
    p_member = Project(
        jira_key="TEN-A-MEMBER",
        name="Member",
        owner_id=999,
        meta={"tenant_id": "tenant-a", "member_ids": [viewer.id]},
    )
    p_hidden_same_tenant = Project(
        jira_key="TEN-A-HIDDEN",
        name="Hidden",
        owner_id=999,
        meta={"tenant_id": "tenant-a", "member_ids": []},
    )
    p_mismatch_tenant = Project(
        jira_key="TEN-B-OWN",
        name="TenantMismatch",
        owner_id=viewer.id,
        meta={"tenant_id": "tenant-b"},
    )
    db_session.add_all([p_owned, p_member, p_hidden_same_tenant, p_mismatch_tenant])
    await db_session.commit()

    response = await client.get("/api/v1/projects/?skip=0&limit=100")
    assert response.status_code == 200, response.text
    returned_ids = {item["id"] for item in response.json()}
    assert p_owned.id in returned_ids
    assert p_member.id in returned_ids
    assert p_hidden_same_tenant.id not in returned_ids
    assert p_mismatch_tenant.id not in returned_ids


@pytest.mark.asyncio
async def test_projects_list_returns_empty_for_zero_limit(
    client, db_session, override_user_dep
):
    viewer = _PermissionUser(user_id=37, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(viewer, tenant_id="tenant-a"))

    project = Project(
        jira_key="TEN-A-LIMIT-0",
        name="Limit Zero",
        owner_id=viewer.id,
        meta={"tenant_id": "tenant-a"},
    )
    db_session.add(project)
    await db_session.commit()

    response = await client.get("/api/v1/projects/?skip=0&limit=0")
    assert response.status_code == 200, response.text
    assert response.json() == []


@pytest.mark.asyncio
async def test_project_detail_denies_tenant_mismatch(client, db_session, override_user_dep):
    viewer = _PermissionUser(user_id=31, permissions={Permissions.PROJECT_VIEW}, is_active=True)
    override_user_dep(_user_dep(viewer, tenant_id="tenant-a"))

    project = Project(
        jira_key="TEN-B-DETAIL",
        name="Tenant B",
        owner_id=viewer.id,
        meta={"tenant_id": "tenant-b"},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    response = await client.get(f"/api/v1/projects/{project.id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_project_create_enforces_owner_and_sets_membership(
    client, override_user_dep
):
    creator = _PermissionUser(user_id=32, permissions={Permissions.PROJECT_CREATE}, is_active=True)
    override_user_dep(_user_dep(creator, tenant_id="tenant-a"))

    forbidden = await client.post(
        "/api/v1/projects/",
        json={"jira_key": "TEN-A-403", "name": "Denied", "owner_id": 999, "meta": {"tenant_id": "tenant-a"}},
    )
    assert forbidden.status_code == 403

    created = await client.post(
        "/api/v1/projects/",
        json={"jira_key": "TEN-A-OK", "name": "Created", "owner_id": creator.id},
    )
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["owner_id"] == creator.id
    assert payload["meta"]["tenant_id"] == "tenant-a"
    assert creator.id in payload["meta"]["member_ids"]


@pytest.mark.asyncio
async def test_scoped_token_admin_role_cannot_set_tenant_without_admin_scope(
    client, override_user_dep
):
    admin_user = _PermissionUser(user_id=33, permissions={Permissions.ADMIN}, is_active=True)
    override_user_dep(
        _user_dep(
            admin_user,
            tenant_id=None,
            token_scopes=[Permissions.PROJECT_VIEW],
        )
    )

    response = await client.post(
        "/api/v1/auth/scoped-token",
        json={"scopes": [Permissions.PROJECT_VIEW], "expires_minutes": 5, "tenant_id": "tenant-z"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Requested tenant_id is not accessible for current user"


@pytest.mark.asyncio
async def test_projects_list_admin_token_is_limited_by_tenant_claim(
    client, db_session, override_user_dep
):
    admin_user = _PermissionUser(
        user_id=34,
        permissions={Permissions.ADMIN, Permissions.PROJECT_VIEW},
        is_active=True,
    )
    override_user_dep(
        _user_dep(
            admin_user,
            tenant_id="tenant-a",
            token_scopes=[Permissions.ADMIN, Permissions.PROJECT_VIEW],
        )
    )

    tenant_a = Project(
        jira_key="TEN-A-ADMIN",
        name="Tenant A",
        owner_id=999,
        meta={"tenant_id": "tenant-a"},
    )
    tenant_b = Project(
        jira_key="TEN-B-ADMIN",
        name="Tenant B",
        owner_id=999,
        meta={"tenant_id": "tenant-b"},
    )
    no_tenant = Project(
        jira_key="TEN-NONE-ADMIN",
        name="No Tenant",
        owner_id=999,
        meta=None,
    )
    db_session.add_all([tenant_a, tenant_b, no_tenant])
    await db_session.commit()

    response = await client.get("/api/v1/projects/?skip=0&limit=100")
    assert response.status_code == 200, response.text

    returned_ids = {item["id"] for item in response.json()}
    assert tenant_a.id in returned_ids
    assert tenant_b.id not in returned_ids
    assert no_tenant.id not in returned_ids


@pytest.mark.asyncio
async def test_baselines_list_requires_project_for_admin_role_with_non_admin_scope(
    client, override_user_dep
):
    admin_user = _PermissionUser(
        user_id=35,
        permissions={Permissions.ADMIN, Permissions.TRACEABILITY_VIEW},
        is_active=True,
    )
    override_user_dep(
        _user_dep(
            admin_user,
            tenant_id=None,
            token_scopes=[Permissions.TRACEABILITY_VIEW],
        )
    )

    response = await client.get("/api/v1/traceability/baselines")
    assert response.status_code == 403
    assert response.json()["detail"] == "project_id is required"


@pytest.mark.asyncio
async def test_baselines_list_requires_project_for_tenant_scoped_admin_token(
    client, override_user_dep
):
    admin_user = _PermissionUser(
        user_id=36,
        permissions={Permissions.ADMIN, Permissions.TRACEABILITY_VIEW},
        is_active=True,
    )
    override_user_dep(
        _user_dep(
            admin_user,
            tenant_id="tenant-a",
            token_scopes=[Permissions.ADMIN, Permissions.TRACEABILITY_VIEW],
        )
    )

    response = await client.get("/api/v1/traceability/baselines")
    assert response.status_code == 403
    assert response.json()["detail"] == "project_id is required"
