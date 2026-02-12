"""
Tests for Git integration endpoints.
"""
import json
import hmac
import hashlib
from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Repository, Commit, PullRequest, Artifact, ArtifactLink


@pytest.fixture
def github_webhook_headers(github_webhook_secret: str):
    """Generate valid GitHub webhook headers."""
    def _headers(body: bytes) -> dict:
        signature = hmac.new(
            github_webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha256
        )
        return {
            "X-Hub-Signature-256": f"sha256={signature.hexdigest()}",
            "X-GitHub-Event": "push"
        }
    return _headers


@pytest.fixture
def github_webhook_secret():
    """GitHub webhook secret for testing."""
    return "test-secret-123"


@pytest.fixture
def gitlab_webhook_headers(gitlab_webhook_secret: str):
    """Generate valid GitLab webhook headers."""
    return {
        "X-Gitlab-Token": gitlab_webhook_secret,
        "Content-Type": "application/json"
    }


@pytest.fixture
def gitlab_webhook_secret():
    """GitLab webhook secret for testing."""
    return "gitlab-secret-456"


class TestGitWebhooks:
    """Test webhook endpoints."""

    async def test_github_push_webhook(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        github_webhook_headers,
        github_webhook_secret,
        monkeypatch
    ):
        """Test GitHub push webhook processing."""
        monkeypatch.setattr("app.core.config.settings.GITHUB_WEBHOOK_SECRET", github_webhook_secret)

        payload = {
            "ref": "refs/heads/main",
            "repository": {
                "full_name": "owner/repo",
                "name": "repo",
                "owner": {"login": "owner"}
            },
            "commits": [
                {
                    "id": "abc123",
                    "message": "Fix bug PROJ-123",
                    "author": {
                        "name": "John Doe",
                        "email": "john@example.com"
                    },
                    "url": "https://github.com/owner/repo/commit/abc123"
                }
            ]
        }

        body = json.dumps(payload).encode("utf-8")
        headers = github_webhook_headers(body)

        response = await client.post(
            "/api/v1/git/webhooks/github",
            content=body,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["event"] == "push"
        assert data["created"] == 1

        # Verify repository was created
        repo = await db_session.get(Repository, 1)
        assert repo is not None
        assert repo.provider == "github"
        assert repo.repo_slug == "owner/repo"

        # Verify commit was created
        commit = await db_session.get(Commit, 1)
        assert commit is not None
        assert commit.sha == "abc123"
        assert commit.author_name == "John Doe"
        assert "PROJ-123" in commit.jira_keys

    async def test_github_pull_request_webhook(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        github_webhook_headers,
        github_webhook_secret,
        monkeypatch
    ):
        """Test GitHub pull request webhook processing."""
        monkeypatch.setattr("app.core.config.settings.GITHUB_WEBHOOK_SECRET", github_webhook_secret)

        payload = {
            "action": "opened",
            "repository": {
                "full_name": "owner/repo"
            },
            "pull_request": {
                "number": 42,
                "title": "Add feature PROJ-456",
                "body": "This fixes PROJ-789",
                "state": "open",
                "user": {"login": "johndoe"},
                "html_url": "https://github.com/owner/repo/pull/42",
                "created_at": "2024-01-01T00:00:00Z",
                "head": {"sha": "def456"}
            }
        }

        body = json.dumps(payload).encode("utf-8")
        headers = github_webhook_headers(body)
        headers["X-GitHub-Event"] = "pull_request"

        response = await client.post(
            "/api/v1/git/webhooks/github",
            content=body,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "pull_request:opened" in data["event"]
        assert set(data["jira_keys"]) == {"PROJ-456", "PROJ-789"}

    async def test_gitlab_push_webhook(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        gitlab_webhook_headers,
        gitlab_webhook_secret,
        monkeypatch
    ):
        """Test GitLab push webhook processing."""
        monkeypatch.setattr("app.core.config.settings.GITLAB_WEBHOOK_SECRET", gitlab_webhook_secret)

        payload = {
            "object_kind": "push",
            "ref": "refs/heads/main",
            "project": {
                "path_with_namespace": "group/project"
            },
            "commits": [
                {
                    "id": "xyz789",
                    "message": "Update docs TASK-111",
                    "author": {
                        "name": "Jane Smith",
                        "email": "jane@example.com"
                    },
                    "url": "https://gitlab.com/group/project/-/commit/xyz789"
                }
            ]
        }

        response = await client.post(
            "/api/v1/git/webhooks/gitlab",
            json=payload,
            headers=gitlab_webhook_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["event"] == "push"

    async def test_invalid_github_signature(
        self,
        client: AsyncClient,
        monkeypatch
    ):
        """Test GitHub webhook with invalid signature."""
        monkeypatch.setattr("app.core.config.settings.GITHUB_WEBHOOK_SECRET", "real-secret")

        payload = {"test": "data"}
        body = json.dumps(payload).encode("utf-8")

        response = await client.post(
            "/api/v1/git/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": "sha256=invalid",
                "X-GitHub-Event": "push"
            }
        )

        assert response.status_code == 401
        assert "Invalid signature" in response.json()["detail"]


class TestGitMetrics:
    """Test metrics endpoints."""

    async def test_pull_request_list(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers
    ):
        """Test listing pull requests."""
        # Create test data
        repo = Repository(provider="github", repo_slug="test/repo")
        db_session.add(repo)
        await db_session.flush()

        pr = PullRequest(
            provider="github",
            repository_id=repo.id,
            number=1,
            title="Test PR",
            state="open",
            author_login="testuser",
            opened_at=datetime.now(),
            cycle_time_hours=24.5,
            lead_time_hours=36.2
        )
        db_session.add(pr)
        await db_session.commit()

        response = await client.get(
            "/api/v1/git/pull-requests",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["pull_requests"]) == 1
        assert data["pull_requests"][0]["number"] == 1
        assert data["pull_requests"][0]["cycle_time_hours"] == 24.5

    async def test_pr_metrics_calculation(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers
    ):
        """Test PR metrics calculation."""
        # Create test PRs with various metrics
        repo = Repository(provider="github", repo_slug="test/repo")
        db_session.add(repo)
        await db_session.flush()

        now = datetime.now()
        for i in range(5):
            pr = PullRequest(
                provider="github",
                repository_id=repo.id,
                number=i + 1,
                title=f"PR {i + 1}",
                state="merged" if i < 3 else "open",
                opened_at=now - timedelta(days=i),
                merged_at=now - timedelta(days=i - 1) if i < 3 else None,
                cycle_time_hours=12.0 + i * 4,
                lead_time_hours=15.0 + i * 4,
                time_to_first_review_hours=2.0 + i,
                rework_count=1 if i % 2 == 0 else 0
            )
            db_session.add(pr)

        await db_session.commit()

        response = await client.get(
            "/api/v1/git/pr-metrics",
            headers=auth_headers,
            params={"since_days": 30}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total"] == 5
        assert data["avg_cycle_time_hours"] > 0
        assert data["avg_lead_time_hours"] > 0
        assert data["rework_rate"] == 0.6  # 3 out of 5 PRs have rework
        assert "merged" in data["by_state"]
        assert "open" in data["by_state"]
        assert len(data["histogram"]["bins"]) == 6
        assert len(data["sample_prs"]) <= 20

    async def test_commits_for_issue(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers
    ):
        """Test getting commits for a JIRA issue."""
        # Create test data
        repo = Repository(provider="github", repo_slug="test/repo")
        db_session.add(repo)
        await db_session.flush()

        commit = Commit(
            repository_id=repo.id,
            sha="abc123def456",
            message="Fix bug PROJ-100",
            author_name="Developer",
            author_email="dev@example.com",
            jira_keys=["PROJ-100"]
        )
        db_session.add(commit)

        # Create artifacts
        issue_artifact = Artifact(
            type="jira_issue",
            source="jira",
            external_id="PROJ-100",
            title="Bug in system"
        )
        commit_artifact = Artifact(
            type="commit",
            source="github",
            external_id="abc123def456",
            title="Fix bug PROJ-100"
        )
        db_session.add(issue_artifact)
        db_session.add(commit_artifact)
        await db_session.flush()

        # Link them
        link = ArtifactLink(
            from_artifact_id=commit_artifact.id,
            to_artifact_id=issue_artifact.id,
            link_type="relates_to",
            confidence=0.9
        )
        db_session.add(link)
        await db_session.commit()

        response = await client.get(
            "/api/v1/git/commits/PROJ-100",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["jira_key"] == "PROJ-100"
        assert len(data["commits"]) == 1
        assert data["commits"][0]["sha"] == "abc123def456"


class TestCIIntegration:
    """Test CI/CD integration endpoints."""

    async def test_ci_results_with_junit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers
    ):
        """Test CI results ingestion with JUnit XML."""
        junit_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <testsuites>
            <testsuite name="MyTestSuite" tests="3" failures="1">
                <testcase classname="com.example.TestClass" name="testMethod1" time="0.123"/>
                <testcase classname="com.example.TestClass" name="testMethod2" time="0.456">
                    <failure message="Expected 5 but got 4">Assertion failed</failure>
                </testcase>
                <testcase classname="com.example.TestClass" name="testMethod3" time="0.789">
                    <skipped/>
                </testcase>
            </testsuite>
        </testsuites>"""

        payload = {
            "provider": "jenkins",
            "commit_sha": "abc123",
            "pr_number": 42,
            "junit_xml": junit_xml,
            "coverage": {
                "line": 85.5,
                "branch": 72.3
            },
            "report_url": "https://jenkins.example.com/job/123"
        }

        response = await client.post(
            "/api/v1/git/ci/results",
            json=payload,
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["tests_created"] == 3
        assert data["tests_passed"] == 1
        assert data["tests_failed"] == 1
        assert data["tests_skipped"] == 1
        assert data["coverage_saved"] is True

    async def test_ci_results_with_cobertura(
        self,
        client: AsyncClient,
        auth_headers
    ):
        """Test CI results with Cobertura coverage."""
        cobertura_xml = """<?xml version="1.0"?>
        <coverage line-rate="0.90" branch-rate="0.85">
            <packages>
                <package>
                    <classes>
                        <class filename="src/main.py" line-rate="0.95">
                            <lines>
                                <line number="1" hits="1"/>
                                <line number="2" hits="1"/>
                                <line number="3" hits="0"/>
                            </lines>
                        </class>
                    </classes>
                </package>
            </packages>
        </coverage>"""

        payload = {
            "provider": "github-actions",
            "commit_sha": "def456",
            "cobertura_xml": cobertura_xml
        }

        response = await client.post(
            "/api/v1/git/ci/results",
            json=payload,
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["coverage_saved"] is True
        assert data["coverage"]["line"] == 90.0
        assert data["coverage"]["branch"] == 85.0


class TestRepositoryManagement:
    """Test repository management endpoints."""

    async def test_list_repositories(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        auth_headers
    ):
        """Test listing repositories."""
        # Create test repositories
        repos = [
            Repository(provider="github", repo_slug="org/repo1", default_branch="main"),
            Repository(provider="gitlab", repo_slug="group/repo2", default_branch="master"),
        ]
        for repo in repos:
            db_session.add(repo)
        await db_session.commit()

        response = await client.get(
            "/api/v1/git/repositories",
            headers=auth_headers
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["repositories"]) == 2

        slugs = {r["slug"] for r in data["repositories"]}
        assert slugs == {"org/repo1", "group/repo2"}


class TestHealthCheck:
    """Test health check endpoint."""

    async def test_git_health_check(self, client: AsyncClient):
        """Test Git module health check."""
        response = await client.get("/api/v1/git/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["module"] == "git"
        assert "webhooks" in data["endpoints"]
        assert "metrics" in data["endpoints"]
        assert "ci" in data["endpoints"]