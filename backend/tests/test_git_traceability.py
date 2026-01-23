import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Artifact, ArtifactLink, Project
from app.api.api_v1.endpoints.git.webhooks import process_commits as create_commit_artifacts, process_pull_request

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:
    engine = create_async_engine(DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session
    await engine.dispose()


async def _create_project_with_issue(session: AsyncSession, issue_key: str) -> Artifact:
    project = Project(jira_key="TRACE", name="Traceability Project")
    session.add(project)
    await session.flush()

    issue = Artifact(
        project_id=project.id,
        type="jira_issue",
        source="jira",
        external_id=issue_key,
        display_key=issue_key,
        title="Sample issue",
        status="To Do",
        tenant_id="default",
    )
    session.add(issue)
    await session.commit()
    await session.refresh(issue)
    return issue


@pytest.mark.asyncio
async def test_create_commit_artifacts_links_to_issue(async_session: AsyncSession):
    issue = await _create_project_with_issue(async_session, "ABC-1")

    result = await create_commit_artifacts(
        async_session,
        provider="github",
        repo_slug="org/repo",
        commits=[
            {
                "id": "1234567890abcdef",
                "message": "ABC-1 fix critical bug",
                "author": {"email": "dev@example.com", "name": "Dev Example"},
                "url": "https://example.com/commit/1234567890abcdef",
            }
        ],
        branch="main",
    )

    assert result["created"] == 1
    assert result["links_created"] == 1
    assert result["suggestions"] == []

    commit_artifact = (
        await async_session.execute(select(Artifact).where(Artifact.type == "commit"))
    ).scalar_one()
    assert commit_artifact.project_id == issue.project_id
    assert commit_artifact.tenant_id == issue.tenant_id
    assert commit_artifact.meta.get("branch") == "main"
    assert commit_artifact.meta.get("repo") == "org/repo"

    link = (await async_session.execute(select(ArtifactLink))).scalar_one()
    assert link.project_id == issue.project_id
    assert link.from_artifact_id == commit_artifact.id
    assert link.to_artifact_id == issue.id


@pytest.mark.asyncio
async def test_upsert_pull_request_artifact_creates_links(async_session: AsyncSession):
    issue = await _create_project_with_issue(async_session, "XYZ-99")

    result = await process_pull_request(
        db=async_session,
        provider="github",
        repo_slug="org/repo",
        pr_data={
            "number": 42,
            "title": "XYZ-99 implement feature",
            "state": "open",
            "html_url": "https://example.com/pr/42",
            "body": "",
            "user": {"login": "testuser"},
            "head": {"ref": "feature/xyz-99"}
        },
        action="opened"
    )

    assert result["links_created"] == 1
    assert result["suggestions"] == []

    await async_session.commit()

    pr_artifact = (
        await async_session.execute(select(Artifact).where(Artifact.type == "pull_request"))
    ).scalar_one()
    assert pr_artifact.display_key == "#42"
    assert pr_artifact.project_id == issue.project_id
    assert pr_artifact.meta.get("repo") == "org/repo"
    assert pr_artifact.meta.get("number") == 42
    assert pr_artifact.meta.get("author") == "testuser"
    assert "XYZ-99" in pr_artifact.meta.get("jira_keys", [])

    link = (
        await async_session.execute(
            select(ArtifactLink).where(ArtifactLink.from_artifact_id == pr_artifact.id)
        )
    ).scalar_one()
    assert link.to_artifact_id == issue.id
