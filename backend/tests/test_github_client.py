import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.github_client import fetch_pull_requests, GitHubAPIError

@pytest.mark.asyncio
async def test_fetch_pull_requests_success(monkeypatch):
    async def fake_get(self, url, headers=None, params=None):
        class Response:
            status_code = 200
            def json(self_inner):
                return [{"number": 1, "title": "Test"}]
        return Response()

    with patch('httpx.AsyncClient.get', new=fake_get):
        pulls = await fetch_pull_requests(token='token', repo_slug='owner/repo')
        assert pulls == [{"number": 1, "title": "Test"}]

@pytest.mark.asyncio
async def test_fetch_pull_requests_handles_auth_error():
    async def fake_get(self, url, headers=None, params=None):
        class Response:
            status_code = 401
            text = 'unauthorized'
        return Response()

    with patch('httpx.AsyncClient.get', new=fake_get):
        with pytest.raises(GitHubAPIError):
            await fetch_pull_requests(token='bad', repo_slug='owner/repo')
