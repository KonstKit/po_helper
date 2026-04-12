from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.api_v1.endpoints.traceability import health as health_module
from app.api.api_v1.endpoints.traceability import links as links_module
from app.core.request_context import (
    reset_token_scopes,
    reset_token_tenant_id,
    set_token_scopes,
    set_token_tenant_id,
)
from app.models import Artifact, Permissions, Project


class _AdminUser:
    is_active = True
    is_superuser = True

    def has_permission(self, _permission: str) -> bool:
        return True


class _ScopedAdminUser:
    is_active = True
    is_superuser = False

    def has_permission(self, _permission: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_sync_health_scopes_projects_and_artifact_counts_by_tenant(db_session):
    tenant_a_project = Project(
        jira_key="TENANT-A",
        name="Tenant A Project",
        meta={"tenant_id": "tenant-a"},
    )
    tenant_b_project = Project(
        jira_key="TENANT-B",
        name="Tenant B Project",
        meta={"tenant_id": "tenant-b"},
    )
    db_session.add_all([tenant_a_project, tenant_b_project])
    await db_session.flush()

    db_session.add_all(
        [
            Artifact(
                project_id=tenant_a_project.id,
                tenant_id="tenant-a",
                type="jira_issue",
                source="jira",
                external_id="TENANT-A-1",
                title="Tenant A issue",
            ),
            Artifact(
                project_id=tenant_b_project.id,
                tenant_id="tenant-b",
                type="jira_issue",
                source="jira",
                external_id="TENANT-B-1",
                title="Tenant B issue",
            ),
        ]
    )
    await db_session.commit()

    token = set_token_tenant_id("tenant-a")
    try:
        payload = await health_module.get_sync_health(
            project_id=None,
            db=db_session,
            current_user=_AdminUser(),
        )
    finally:
        reset_token_tenant_id(token)

    assert payload["summary"]["total_artifacts"] == 1
    assert [project["jira_key"] for project in payload["projects"]] == ["TENANT-A"]
    assert payload["projects"][0]["artifact_count"] == 1
    jira_source = next(source for source in payload["sources"] if source["source"] == "jira")
    assert jira_source["artifact_count"] == 1


@pytest.mark.asyncio
async def test_sync_health_accepts_scope_based_admin_without_project_id(db_session):
    token = set_token_scopes((Permissions.ADMIN,))
    try:
        payload = await health_module.get_sync_health(
            project_id=None,
            db=db_session,
            current_user=_ScopedAdminUser(),
        )
    finally:
        reset_token_scopes(token)

    assert payload["summary"]["total_sources"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("builder_name", "validator_name", "kind"),
    [
        ("_build_jira_source_health", "_validate_jira_connection", "jira"),
        ("_build_confluence_source_health", "_validate_confluence_connection", "confluence"),
    ],
)
async def test_source_health_offloads_blocking_validation_to_worker_thread(
    db_session,
    monkeypatch,
    builder_name: str,
    validator_name: str,
    kind: str,
):
    async def _fake_overrides(*_args, **_kwargs):
        return SimpleNamespace(
            enabled=True,
            settings={
                "base_url": f"https://{kind}.example.com",
                "api_token": f"{kind}-token",
                "email": f"{kind}@example.com",
            },
        )

    observed: dict[str, object] = {}

    async def _fake_to_thread(func, *args):
        observed["func"] = func
        observed["args"] = args
        return None

    monkeypatch.setattr(health_module, "get_connector_overrides", _fake_overrides)
    monkeypatch.setattr(health_module.asyncio, "to_thread", _fake_to_thread)

    builder = getattr(health_module, builder_name)
    validator = getattr(health_module, validator_name)
    result = await builder(
        db_session,
        project_id=42,
        integration=None,
        artifact_count=3,
        last_sync=None,
        checked_at="2026-04-12T00:00:00",
    )

    assert observed["func"] is validator
    expected_email = None if kind == "jira" and getattr(health_module.settings, "JIRA_FORCE_PAT", True) else f"{kind}@example.com"
    assert observed["args"] == (
        f"https://{kind}.example.com",
        expected_email,
        f"{kind}-token",
    )
    assert result["status"] == "reachable"
    assert result["effective_connector_source"] == "project_override"


@pytest.mark.asyncio
async def test_manual_repair_does_not_trigger_git_post_sync_twice(db_session, monkeypatch):
    async def _fake_ensure_project_access(project_id, _db, _current_user):
        return SimpleNamespace(id=project_id)

    class _ArtifactSyncService:
        async def sync_jira_project_artifacts(self, *_args, **_kwargs):
            return SimpleNamespace(created=0, updated=0, warnings=[])

        async def sync_confluence_project_artifacts(self, *_args, **_kwargs):
            return SimpleNamespace(created=0, updated=0, warnings=[])

    class _FakeGitSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    git_result = {
        "project_id": 123,
        "repositories": [
            {
                "repository_id": 1,
                "commits": {"created": 2, "updated": 0},
                "pull_requests": {"processed": 1},
            }
        ],
    }
    post_sync_mock = AsyncMock()

    monkeypatch.setattr(links_module, "ensure_project_access", _fake_ensure_project_access)
    monkeypatch.setattr(
        links_module,
        "get_traceability_artifact_sync_service",
        lambda: _ArtifactSyncService(),
    )
    monkeypatch.setattr(links_module, "AsyncSessionLocal", lambda: _FakeGitSessionContext())
    monkeypatch.setattr(links_module.git_import_service, "sync_project", AsyncMock(return_value=git_result))
    monkeypatch.setattr(links_module, "run_traceability_post_sync", post_sync_mock)

    response = await links_module.backfill_artifacts(
        request=SimpleNamespace(),
        project_id=123,
        include_confluence=False,
        include_git=True,
        db=db_session,
        current_user=_AdminUser(),
    )

    payload = json.loads(response.body.decode())
    assert payload["git"]["repositories"][0]["commits"]["created"] == 2
    assert post_sync_mock.await_count == 0
