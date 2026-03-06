from __future__ import annotations

import pytest

from app.core.crypto import encrypt_str
from app.core.database import AsyncSessionLocal
from app.models import IntegrationSetting, Project


@pytest.mark.asyncio
async def test_github_pulls_returns_empty_when_github_not_configured(client):
    response = await client.get("/api/v1/git/github/projects/1/pulls")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0
    assert payload["pulls"] == []
    assert payload["reason"] == "github_not_configured"


@pytest.mark.asyncio
async def test_github_pulls_returns_empty_when_project_has_no_github_repository(client):
    async with AsyncSessionLocal() as session:
        project = Project(jira_key="GH-EMPTY", name="No GitHub Repo", status="active")
        session.add(project)
        session.add(
            IntegrationSetting(
                kind="github",
                base_url="https://api.github.com",
                api_token=encrypt_str("ghp_dummy_token"),
            )
        )
        await session.commit()
        await session.refresh(project)
        project_id = project.id

    response = await client.get(f"/api/v1/git/github/projects/{project_id}/pulls")

    assert response.status_code == 200
    payload = response.json()
    assert payload["repository"] == ""
    assert payload["count"] == 0
    assert payload["pulls"] == []
    assert payload["reason"] == "no_github_repository_linked"
