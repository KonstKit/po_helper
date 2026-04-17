from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.api_v1.endpoints.traceability import health as health_module
from app.api.api_v1.endpoints.traceability import orphans as orphans_module
from app.core.database import Base
from app.models import Artifact, ArtifactLink, Project


@dataclass
class _AdminUser:
    is_active: bool = True
    is_superuser: bool = True

    def has_permission(self, _permission: str) -> bool:
        return True

    def has_role(self, _role: str) -> bool:
        return False


async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    session = session_factory()
    session._test_engine = engine  # type: ignore[attr-defined]
    return session


async def _close_session(session: AsyncSession) -> None:
    engine = getattr(session, "_test_engine", None)
    await session.close()
    if engine is not None:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sync_health_returns_canonical_shape():
    session = await _make_session()
    try:
        project = Project(jira_key="SYNC", name="Sync Health Project", status="active")
        session.add(project)
        await session.flush()

        session.add(
            Artifact(
                project_id=project.id,
                type="jira_issue",
                source="jira",
                external_id="SYNC-1",
                display_key="SYNC-1",
                title="Sync issue",
            )
        )
        await session.commit()

        payload = await health_module.get_sync_health(
            project_id=None,
            db=session,
            current_user=_AdminUser(),
        )
    finally:
        await _close_session(session)

    assert set(payload.keys()) == {"health", "summary", "sources", "projects"}
    assert set(payload["health"].keys()) == {"status", "score"}
    assert set(payload["summary"].keys()) == {
        "total_sources",
        "reachable_sources",
        "total_artifacts",
        "last_sync",
        "checked_at",
    }
    assert payload["summary"]["total_artifacts"] == 1
    assert len(payload["projects"]) == 1
    assert payload["projects"][0]["project_id"] == project.id
    assert payload["projects"][0]["artifact_count"] == 1

    required_source_keys = {
        "source",
        "label",
        "status",
        "effective_connector_source",
        "artifact_count",
        "last_sync",
        "checked_at",
        "error",
    }
    for source in payload["sources"]:
        assert required_source_keys.issubset(source.keys())
        assert source["status"] in {"not_configured", "reachable", "degraded"}


@pytest.mark.asyncio
async def test_confidence_distribution_returns_canonical_shape():
    session = await _make_session()
    try:
        project = Project(jira_key="CONF", name="Confidence Project", status="active")
        session.add(project)
        await session.flush()

        artifacts = [
            Artifact(
                project_id=project.id,
                type="jira_issue",
                source="jira",
                external_id="CONF-1",
                display_key="CONF-1",
                title="Issue 1",
            ),
            Artifact(
                project_id=project.id,
                type="commit",
                source="github",
                external_id="sha-1",
                display_key="sha-1",
                title="Commit 1",
            ),
            Artifact(
                project_id=project.id,
                type="confluence_page",
                source="confluence",
                external_id="PAGE-1",
                display_key="PAGE-1",
                title="Page 1",
            ),
            Artifact(
                project_id=project.id,
                type="test_case",
                source="testrail",
                external_id="TC-1",
                display_key="TC-1",
                title="Test Case 1",
            ),
        ]
        session.add_all(artifacts)
        await session.flush()

        session.add_all(
            [
                ArtifactLink(
                    project_id=project.id,
                    from_artifact_id=artifacts[1].id,
                    to_artifact_id=artifacts[0].id,
                    link_type="implements",
                    confidence=0.1,
                    created_via="manual",
                ),
                ArtifactLink(
                    project_id=project.id,
                    from_artifact_id=artifacts[3].id,
                    to_artifact_id=artifacts[2].id,
                    link_type="tests",
                    confidence=0.9,
                    created_via="manual",
                ),
                ArtifactLink(
                    project_id=project.id,
                    from_artifact_id=artifacts[2].id,
                    to_artifact_id=artifacts[0].id,
                    link_type="relates_to",
                    confidence=None,
                    created_via="manual",
                ),
            ]
        )
        await session.commit()

        payload = await orphans_module.get_confidence_distribution(
            project_id=None,
            db=session,
            current_user=_AdminUser(),
        )
    finally:
        await _close_session(session)

    assert set(payload.keys()) == {"histogram", "stats", "by_link_type"}
    assert [bucket["range"] for bucket in payload["histogram"]] == [
        "0.0-0.2",
        "0.2-0.4",
        "0.4-0.6",
        "0.6-0.8",
        "0.8-1.0",
    ]
    assert set(payload["stats"].keys()) == {
        "total_links",
        "avg_confidence",
        "median_confidence",
        "min_confidence",
        "max_confidence",
    }
    assert payload["stats"]["total_links"] == 3
    assert payload["stats"]["avg_confidence"] == pytest.approx(0.5)
    assert payload["stats"]["median_confidence"] == pytest.approx(0.5)
    assert payload["stats"]["min_confidence"] == pytest.approx(0.1)
    assert payload["stats"]["max_confidence"] == pytest.approx(0.9)

    assert set(payload["by_link_type"].keys()) == {"implements", "tests", "relates_to"}
    assert set(payload["by_link_type"]["implements"].keys()) == {"count", "avg_confidence"}
    assert payload["by_link_type"]["implements"]["count"] == 1
    assert payload["by_link_type"]["implements"]["avg_confidence"] == pytest.approx(0.1)
    assert payload["by_link_type"]["tests"]["avg_confidence"] == pytest.approx(0.9)
    assert payload["by_link_type"]["relates_to"]["avg_confidence"] == pytest.approx(0.0)
