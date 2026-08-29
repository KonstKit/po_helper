import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select

from app.core.database import Base
from app.core.crypto import encrypt_str
from app.models import (
    Artifact,
    ArtifactLink,
    IntegrationSetting,
    Project,
    ProjectRepository,
    Repository,
)
from app.services.git_import_service import git_import_service

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture()
async def async_session() -> AsyncSession:
    engine = create_async_engine(DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_project_imports_commits_and_prs(monkeypatch, async_session: AsyncSession):
    project = Project(jira_key="TRACE", name="Traceability Project")
    async_session.add(project)
    await async_session.flush()

    issue = Artifact(
        project_id=project.id,
        type="jira_issue",
        source="jira",
        external_id="TRACE-1",
        display_key="TRACE-1",
        title="Example issue",
        status="To Do",
    )
    async_session.add(issue)

    repository = Repository(provider="github", repo_slug="org/repo", default_branch="main")
    async_session.add(repository)
    await async_session.flush()

    project_repo = ProjectRepository(
        project_id=project.id, repository_id=repository.id, is_primary=True
    )
    async_session.add(project_repo)

    token_bundle = json.dumps({"api_token": "dummy-token"})
    integration = IntegrationSetting(
        kind="github",
        base_url="https://api.github.com",
        api_token=encrypt_str(token_bundle),
    )
    async_session.add(integration)
    await async_session.commit()

    commit_payload = [
        {
            "id": "abcdef1234567890",
            "sha": "abcdef1234567890",
            "message": "TRACE-1 implement feature",
            "author": {"email": "dev@example.com", "name": "Dev"},
            "url": "https://example.com/commit/abcdef1234567890",
        }
    ]

    pr_payload = [
        {
            "number": 42,
            "title": "TRACE-1 add capability",
            "state": "open",
            "body": "Implements TRACE-1",
            "html_url": "https://example.com/pr/42",
            "user": {"login": "dev"},
            "head": {"ref": "feature/trace-1"},
        }
    ]

    monkeypatch.setattr(
        git_import_service, "_fetch_github_commits", lambda config, repo_slug: commit_payload
    )
    monkeypatch.setattr(
        git_import_service, "_fetch_github_pull_requests", lambda config, repo_slug: pr_payload
    )

    async def _fake_ensure_branch(db: AsyncSession, repo: Repository, config):
        return repo.default_branch or "main"

    monkeypatch.setattr(git_import_service, "_ensure_default_branch", _fake_ensure_branch)

    result = await git_import_service.sync_project(async_session, project.id)

    assert result["project_id"] == project.id
    assert result["repositories"], "Expected repository summary in result"
    summary = result["repositories"][0]
    assert summary["commits"]["created"] == 1
    assert summary["pull_requests"]["processed"] == 1

    commit_artifact = (
        await async_session.execute(select(Artifact).where(Artifact.type == "commit"))
    ).scalar_one()
    assert commit_artifact.meta.get("jira_keys") == ["TRACE-1"]

    pr_artifact = (
        await async_session.execute(select(Artifact).where(Artifact.type == "pull_request"))
    ).scalar_one()
    assert pr_artifact.meta.get("repo") == "org/repo"

    link_count = (await async_session.execute(select(ArtifactLink))).scalars().all()
    assert len(link_count) >= 2
