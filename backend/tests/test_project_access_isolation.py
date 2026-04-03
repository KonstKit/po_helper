from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import can_access_project, ensure_project_access
from app.core.request_context import (
    reset_token_scopes,
    reset_token_tenant_id,
    set_token_scopes,
    set_token_tenant_id,
)
from app.models.project import Project


def _fake_user(*, user_id: int, is_active: bool = True, is_superuser: bool = False):
    return SimpleNamespace(
        id=user_id,
        is_active=is_active,
        is_superuser=is_superuser,
        has_permission=lambda _perm: False,
    )


def test_can_access_project_requires_tenant_claim_for_tenant_scoped_project():
    project = SimpleNamespace(owner_id=7, meta={"tenant_id": "tenant-a", "member_ids": [7]})
    user = _fake_user(user_id=7)

    scopes_token = set_token_scopes(None)
    tenant_token = set_token_tenant_id(None)
    try:
        assert can_access_project(project, user) is False
    finally:
        reset_token_scopes(scopes_token)
        reset_token_tenant_id(tenant_token)


def test_can_access_project_allows_owner_when_tenant_matches():
    project = SimpleNamespace(owner_id=7, meta={"tenant_id": "tenant-a", "member_ids": [7]})
    user = _fake_user(user_id=7)

    scopes_token = set_token_scopes(None)
    tenant_token = set_token_tenant_id("tenant-a")
    try:
        assert can_access_project(project, user) is True
    finally:
        reset_token_scopes(scopes_token)
        reset_token_tenant_id(tenant_token)


@pytest.mark.asyncio
async def test_ensure_project_access_denies_tenant_project_without_claim(db_session):
    project = Project(jira_key="TEN-1", name="Tenant Project", owner_id=11, meta={"tenant_id": "t1"})
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    user = _fake_user(user_id=11)
    scopes_token = set_token_scopes(None)
    tenant_token = set_token_tenant_id(None)
    try:
        with pytest.raises(HTTPException) as exc_info:
            await ensure_project_access(project.id, db_session, user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Tenant-scoped token is required"
    finally:
        reset_token_scopes(scopes_token)
        reset_token_tenant_id(tenant_token)
