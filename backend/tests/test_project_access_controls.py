from __future__ import annotations

from typing import Callable, Optional, Set

import pytest

from app.api.deps import get_current_user
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


class _ProjectUser:
    def __init__(
        self,
        user_id: int,
        permissions: Set[str],
        *,
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
async def test_projects_list_filters_to_accessible_projects(client, db_session, override_user_dep):
    db_session.add_all(
        [
            Project(jira_key="PJT-1", name="Visible", owner_id=2, meta={"member_ids": [100]}),
            Project(jira_key="PJT-2", name="Hidden", owner_id=2, meta={"member_ids": [999]}),
        ]
    )
    await db_session.commit()

    viewer = _ProjectUser(100, {Permissions.PROJECT_VIEW})
    override_user_dep(lambda: viewer)

    response = await client.get("/api/v1/projects/?skip=0&limit=50")
    payload = response.json()

    assert response.status_code == 200
    assert [project["jira_key"] for project in payload] == ["PJT-1"]


@pytest.mark.asyncio
async def test_create_project_rejects_owner_mismatch_for_non_admin(client, override_user_dep):
    creator = _ProjectUser(7, {Permissions.PROJECT_CREATE})
    override_user_dep(lambda: creator)

    response = await client.post(
        "/api/v1/projects/",
        json={
            "jira_key": "PJT-3",
            "name": "Owner Mismatch",
            "description": "Should be rejected",
            "owner_id": 99,
            "meta": {},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "owner_id must match current user"


@pytest.mark.asyncio
async def test_create_project_rejects_tenant_mismatch(client, override_user_dep, monkeypatch):
    creator = _ProjectUser(8, {Permissions.PROJECT_CREATE})
    override_user_dep(lambda: creator)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.projects.get_token_tenant_id",
        lambda: "tenant-a",
    )

    response = await client.post(
        "/api/v1/projects/",
        json={
            "jira_key": "PJT-4",
            "name": "Tenant Mismatch",
            "description": "Should be rejected",
            "owner_id": 8,
            "meta": {"tenant_id": "tenant-b"},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Project tenant mismatch"
