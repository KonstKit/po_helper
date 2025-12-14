import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_jira_status_unconfigured():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/v1/jira/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("configured") is False
    assert data.get("auth_mode") in {"none", "PAT", "Basic"}


@pytest.mark.asyncio
async def test_jira_project_check_unconfigured():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/v1/jira/projects/FOO/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("exists") is False
    assert "detail" in data

