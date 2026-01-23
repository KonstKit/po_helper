"""
Tests for Bitbucket integration.

Covers:
- Bitbucket client functions (Cloud and Server)
- Bitbucket webhook handling
- Bitbucket settings endpoints
"""
import json
import hmac
import hashlib
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import httpx

from app.services.bitbucket_client import (
    detect_instance_type,
    get_api_base,
    build_headers,
    BitbucketType,
    BitbucketAuth,
    BitbucketAPIError,
    test_connection as bitbucket_test_connection,
    fetch_pull_requests,
    fetch_commits,
    fetch_branches,
    fetch_repositories,
)


class TestBitbucketClientHelpers:
    """Test helper functions."""

    def test_detect_cloud_from_bitbucket_org(self):
        """Test Cloud detection from bitbucket.org URL."""
        assert detect_instance_type("https://bitbucket.org") == BitbucketType.CLOUD
        assert detect_instance_type("https://api.bitbucket.org/2.0") == BitbucketType.CLOUD
        assert detect_instance_type("https://BITBUCKET.ORG/workspace") == BitbucketType.CLOUD

    def test_detect_server_from_custom_url(self):
        """Test Server detection from custom URL."""
        assert detect_instance_type("https://bitbucket.company.com") == BitbucketType.SERVER
        assert detect_instance_type("https://git.internal.corp") == BitbucketType.SERVER
        assert detect_instance_type("http://localhost:7990") == BitbucketType.SERVER

    def test_get_api_base_cloud(self):
        """Test API base URL for Cloud."""
        base = get_api_base("https://bitbucket.org", BitbucketType.CLOUD)
        assert base == "https://api.bitbucket.org/2.0"

    def test_get_api_base_server(self):
        """Test API base URL for Server."""
        base = get_api_base("https://bitbucket.company.com", BitbucketType.SERVER)
        assert base == "https://bitbucket.company.com/rest/api/latest"

        # Already has API path
        base = get_api_base("https://bitbucket.company.com/rest/api/1.0", BitbucketType.SERVER)
        assert base == "https://bitbucket.company.com/rest/api/1.0"

    def test_build_headers_cloud_basic_auth(self):
        """Test headers for Cloud with app password."""
        auth = BitbucketAuth(
            instance_type=BitbucketType.CLOUD,
            base_url="https://bitbucket.org",
            username="user@example.com",
            app_password="app-password-123",
        )
        headers = build_headers(auth)

        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")
        assert headers["Accept"] == "application/json"

    def test_build_headers_cloud_oauth(self):
        """Test headers for Cloud with OAuth token."""
        auth = BitbucketAuth(
            instance_type=BitbucketType.CLOUD,
            base_url="https://bitbucket.org",
            access_token="oauth-token-abc",
        )
        headers = build_headers(auth)

        assert headers["Authorization"] == "Bearer oauth-token-abc"

    def test_build_headers_server_pat(self):
        """Test headers for Server with PAT."""
        auth = BitbucketAuth(
            instance_type=BitbucketType.SERVER,
            base_url="https://bitbucket.company.com",
            access_token="personal-access-token",
        )
        headers = build_headers(auth)

        assert headers["Authorization"] == "Bearer personal-access-token"


class TestBitbucketClientAPI:
    """Test API client functions."""

    @pytest.mark.asyncio
    async def test_test_connection_cloud_success(self):
        """Test successful Cloud connection."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "username": "testuser",
            "display_name": "Test User",
            "account_id": "abc123",
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            result = await bitbucket_test_connection(
                base_url="https://bitbucket.org",
                username="user@example.com",
                app_password="password",
            )

            assert result["status"] == "connected"
            assert result["instance_type"] == "cloud"
            assert result["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_test_connection_auth_failure(self):
        """Test connection with invalid credentials."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            with pytest.raises(BitbucketAPIError) as exc:
                await bitbucket_test_connection(
                    base_url="https://bitbucket.org",
                    username="user",
                    app_password="wrong",
                )
            assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_test_connection_no_credentials(self):
        """Test connection without credentials."""
        with pytest.raises(BitbucketAPIError) as exc:
            await bitbucket_test_connection(base_url="https://bitbucket.org")
        assert "No authentication" in str(exc.value)

    @pytest.mark.asyncio
    async def test_fetch_pull_requests_cloud(self):
        """Test fetching PRs from Cloud."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "values": [
                {"id": 1, "title": "PR 1", "state": "OPEN"},
                {"id": 2, "title": "PR 2", "state": "MERGED"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            prs = await fetch_pull_requests(
                base_url="https://bitbucket.org",
                workspace="myteam",
                repo_slug="myrepo",
                username="user",
                app_password="pass",
            )

            assert len(prs) == 2
            assert prs[0]["title"] == "PR 1"

    @pytest.mark.asyncio
    async def test_fetch_commits(self):
        """Test fetching commits."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "values": [
                {"hash": "abc123", "message": "Commit 1"},
                {"hash": "def456", "message": "Commit 2"},
            ]
        }

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            mock_client.return_value = mock_instance

            commits = await fetch_commits(
                base_url="https://bitbucket.org",
                workspace="myteam",
                repo_slug="myrepo",
                access_token="token",
            )

            assert len(commits) == 2
            assert commits[0]["hash"] == "abc123"


class TestBitbucketWebhook:
    """Test Bitbucket webhook handling."""

    @pytest.fixture
    def bitbucket_webhook_secret(self):
        """Bitbucket webhook secret for testing."""
        return "bitbucket-secret-789"

    @pytest.fixture
    def bitbucket_webhook_headers(self, bitbucket_webhook_secret: str):
        """Generate valid Bitbucket webhook headers."""
        def _headers(body: bytes) -> dict:
            signature = hmac.new(
                bitbucket_webhook_secret.encode("utf-8"),
                msg=body,
                digestmod=hashlib.sha256
            )
            return {
                "X-Hub-Signature": f"sha256={signature.hexdigest()}",
                "X-Event-Key": "repo:push"
            }
        return _headers

    async def test_bitbucket_push_webhook(
        self,
        client,
        db_session,
        bitbucket_webhook_headers,
        bitbucket_webhook_secret,
        monkeypatch
    ):
        """Test Bitbucket push webhook processing."""
        monkeypatch.setattr(
            "app.core.config.settings.BITBUCKET_WEBHOOK_SECRET",
            bitbucket_webhook_secret
        )

        payload = {
            "repository": {
                "full_name": "workspace/repo"
            },
            "push": {
                "changes": [
                    {
                        "new": {
                            "name": "main",
                            "type": "branch"
                        },
                        "commits": [
                            {
                                "hash": "abc123",
                                "message": "Fix issue PROJ-100",
                                "author": {
                                    "user": {"display_name": "John Doe"},
                                    "raw": "John Doe <john@example.com>"
                                },
                                "links": {
                                    "html": {"href": "https://bitbucket.org/workspace/repo/commits/abc123"}
                                }
                            }
                        ]
                    }
                ]
            }
        }

        body = json.dumps(payload).encode("utf-8")
        headers = bitbucket_webhook_headers(body)

        response = await client.post(
            "/api/v1/git/webhooks/bitbucket",
            content=body,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["event"] == "repo:push"

    async def test_bitbucket_pr_webhook(
        self,
        client,
        db_session,
        bitbucket_webhook_headers,
        bitbucket_webhook_secret,
        monkeypatch
    ):
        """Test Bitbucket pull request webhook."""
        monkeypatch.setattr(
            "app.core.config.settings.BITBUCKET_WEBHOOK_SECRET",
            bitbucket_webhook_secret
        )

        payload = {
            "repository": {
                "full_name": "workspace/repo"
            },
            "pullrequest": {
                "id": 42,
                "title": "Add feature PROJ-200",
                "description": "This implements the feature",
                "state": "OPEN",
                "author": {"display_name": "Jane Doe"},
                "links": {
                    "html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/42"}
                },
                "created_on": "2024-01-01T00:00:00Z"
            }
        }

        body = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            bitbucket_webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256
        )
        headers = {
            "X-Hub-Signature": f"sha256={signature.hexdigest()}",
            "X-Event-Key": "pullrequest:created"
        }

        response = await client.post(
            "/api/v1/git/webhooks/bitbucket",
            content=body,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "pullrequest:created" in data["event"]


class TestBitbucketSettings:
    """Test Bitbucket settings endpoints."""

    async def test_get_bitbucket_settings(self, client, auth_headers):
        """Test getting Bitbucket settings."""
        response = await client.get(
            "/api/v1/settings/bitbucket",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["kind"] == "bitbucket"

    async def test_put_bitbucket_settings(self, client, auth_headers):
        """Test updating Bitbucket settings."""
        response = await client.put(
            "/api/v1/settings/bitbucket",
            headers=auth_headers,
            json={
                "base_url": "https://bitbucket.org",
                "email": "user@example.com",
                "api_token": "app-password-123"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["kind"] == "bitbucket"
        assert data["base_url"] == "https://bitbucket.org"
        assert data["has_token"] is True

    async def test_test_bitbucket_connection(self, client, auth_headers, monkeypatch):
        """Test Bitbucket connection test endpoint."""
        # Mock the connection test
        async def mock_test_connection(*args, **kwargs):
            return {
                "status": "connected",
                "instance_type": "cloud",
                "username": "testuser"
            }

        monkeypatch.setattr(
            "app.services.bitbucket_client.test_connection",
            mock_test_connection
        )

        response = await client.post(
            "/api/v1/settings/bitbucket/test",
            headers=auth_headers,
            json={
                "base_url": "https://bitbucket.org",
                "email": "user@example.com",
                "api_token": "password"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["success", "ok", "connected"]
