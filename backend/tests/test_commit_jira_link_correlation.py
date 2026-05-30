"""Regression: commit -> jira_issue links must correlate to the referenced key.

A ``commitSource -> jiraKeyExtractor -> createLinkAction`` flow flattens the Jira
keys from *all* input commits into one set, so without correlation
``createLinkAction`` links EVERY commit to EVERY extracted key — a cartesian
product (e.g. 18 commits + 18 keys -> 324 links instead of 18). The first demo
masked this because it had a single commit (1x1).

``CreateLinkActionExecutor._create_link`` now only creates a commit -> jira_issue
link when the commit's own text (message/branch/description/title) references
that key, so each commit links solely to the issue it mentions.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, SessionLocal
from app.models.project import Project
from app.models.traceability import Artifact, ArtifactLink
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.create_link_action import (
    CreateLinkActionExecutor,
)


@pytest_asyncio.fixture
async def commit_and_two_jira(db_session):
    """A commit whose message references WAB-100, plus jira WAB-100 (referenced)
    and WAB-200 (NOT referenced)."""
    project = Project(jira_key="WAB", name="WaBank")
    db_session.add(project)
    await db_session.flush()

    commit = Artifact(
        project_id=project.id,
        type="commit",
        source="git",
        external_id="sha-aaa",
        title="feat: registration work",
        meta={"message": "feat(reg): implement WAB-100 backend + tests", "branch": "main"},
    )
    jira_ref = Artifact(
        project_id=project.id,
        type="jira_issue",
        source="jira",
        external_id="WAB-100",
        display_key="WAB-100",
        title="Referenced issue",
    )
    jira_other = Artifact(
        project_id=project.id,
        type="jira_issue",
        source="jira",
        external_id="WAB-200",
        display_key="WAB-200",
        title="Unrelated issue",
    )
    db_session.add_all([commit, jira_ref, jira_other])
    await db_session.flush()
    ids = (commit.id, jira_ref.id, jira_other.id)
    await db_session.commit()
    return ids


def _try_link(commit_id: int, jira_id: int) -> int:
    """Run ``_create_link(commit -> jira, 'implements')`` in a fresh sync session;
    return the resulting ArtifactLink row count for the pair."""
    with SessionLocal() as db:
        source = db.query(Artifact).filter(Artifact.id == commit_id).one()
        target = db.query(Artifact).filter(Artifact.id == jira_id).one()
        context = ExecutionContext(rule_id=1, db=db, edges=[])
        CreateLinkActionExecutor()._create_link(source, target, "implements", context)
        db.commit()
        return (
            db.query(ArtifactLink)
            .filter(
                ArtifactLink.from_artifact_id == commit_id,
                ArtifactLink.to_artifact_id == jira_id,
                ArtifactLink.link_type == "implements",
            )
            .count()
        )


@pytest.mark.asyncio
async def test_commit_links_only_to_referenced_jira_key(commit_and_two_jira):
    commit_id, jira_ref_id, jira_other_id = commit_and_two_jira

    # The commit message references WAB-100 -> the link IS created.
    assert _try_link(commit_id, jira_ref_id) == 1

    # The commit does NOT reference WAB-200 -> the link is SKIPPED (no cartesian).
    assert _try_link(commit_id, jira_other_id) == 0

    # Exactly one link exists overall.
    async with AsyncSessionLocal() as s:
        total = (await s.execute(select(func.count()).select_from(ArtifactLink))).scalar()
    assert total == 1
