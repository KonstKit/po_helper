"""Regression: LinkService.create_link must dedupe even when tenant_id is NULL.

The ``uq_artifact_link`` unique constraint includes ``tenant_id``, and under SQL
NULL semantics two rows with a NULL ``tenant_id`` do not collide — so for
single-tenant/local installs (tenant_id always NULL) the constraint alone does
NOT prevent duplicate links. The rule-engine path is already protected by
``createLinkAction._create_link``'s explicit existence check (proven in
``test_sync_redelivery_idempotency.py``); this module proves the *direct*
``LinkService.create_link`` path now has the same protection.

Decision under test: ``create_link`` *raises* ``ValueError("Link already
exists: ...")`` on a duplicate (rather than returning the existing link). That
keeps its contract identical to the pre-existing ``IntegrityError`` path and so
``create_links_batch``'s "already exists" skip logic keeps working unchanged.

Convention mirrors ``test_sync_redelivery_idempotency.py``: each ``create_link``
runs in its own committed session (mimicking two independent direct callers),
and the row count is read from a fresh session to avoid WAL snapshot staleness.
``create_link`` is async, so its own session is an ``AsyncSessionLocal()`` rather
than the sync ``SessionLocal`` the rule-engine test uses.

Coverage: the explicit-project tuple; the project-resolved-from-source branch
(``project_id`` omitted -> ``from_artifact.project_id``); and the pure
NULL-project / NULL-tenant branch (both ``IS NULL``, so ``uq_artifact_link``
gives zero coverage and dedup rests entirely on the existence check's ``IS NULL``
comparisons). The dedup is *sequential only* — a truly concurrent NULL-tenant
insert is a known, documented limitation (see the ``create_link`` docstring's
"Idempotency (sequential only)" note) and is intentionally not exercised here.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.traceability import Artifact, ArtifactLink
from app.services.traceability.link_service import LinkService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _link_count(*, project_id: int | None = None) -> int:
    """Count ArtifactLink rows from a fresh session (avoids WAL staleness).

    With ``project_id`` omitted this counts ALL rows — used for the pure
    NULL-project case, where filtering by ``project_id`` is impossible (the test
    relies on the per-test schema reset so the total equals this test's links).
    """
    async with AsyncSessionLocal() as s:
        stmt = select(func.count()).select_from(ArtifactLink)
        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)
        return (await s.execute(stmt)).scalar()


async def _all_links() -> list[ArtifactLink]:
    """Return every ArtifactLink row from a fresh session.

    The autouse schema reset gives each test a clean table, so the returned list
    is exactly the links the test created — handy for asserting the resolved
    ``project_id`` / ``tenant_id`` on the stored row.
    """
    async with AsyncSessionLocal() as s:
        return list((await s.execute(select(ArtifactLink))).scalars().all())


async def _create_link_via_service(
    a_id: int,
    b_id: int,
    project_id: int | None = None,
    *,
    link_type: str = "relates_to",
) -> None:
    """Run ``LinkService.create_link`` for (a -> b) in its own committed session.

    ``tenant_id`` is left NULL — the single-tenant/local scenario in which the
    unique constraint does not dedupe. ``project_id`` may be ``None`` to exercise
    the resolve-from-source branch (``create_link`` then stores
    ``from_artifact.project_id``). Each call gets its own committed session,
    mimicking a separate direct caller. Confidence is supplied explicitly so the
    test isolates the dedup behaviour (the existence check runs before any
    confidence work regardless).
    """
    async with AsyncSessionLocal() as db:
        service = LinkService(db)
        await service.create_link(
            from_artifact_id=a_id,
            to_artifact_id=b_id,
            link_type=link_type,
            tenant_id=None,
            project_id=project_id,
            confidence=0.9,
            calculate_confidence=False,
            create_audit=False,
        )
        await db.commit()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def project_with_two_artifacts(db_session):
    """A project plus two artifacts (A, B) under it, committed."""
    project = Project(jira_key="NTD", name="Null-Tenant Dedup Project")
    db_session.add(project)
    await db_session.flush()

    art_a = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-A",
        title="Requirement A",
    )
    art_b = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-B",
        title="Requirement B",
    )
    db_session.add_all([art_a, art_b])
    await db_session.flush()
    project_id, a_id, b_id = project.id, art_a.id, art_b.id
    await db_session.commit()
    return project_id, a_id, b_id


@pytest_asyncio.fixture
async def two_artifacts_no_project(db_session):
    """Two artifacts (A, B) with NULL project_id (and NULL tenant_id), committed.

    Used for the pure-NULL dedup path: with ``project_id`` omitted on
    ``create_link`` the stored link ends up with ``project_id IS NULL`` and
    ``tenant_id IS NULL``, so ``uq_artifact_link`` offers no protection at all.
    """
    art_a = Artifact(
        project_id=None,
        type="requirement",
        source="internal",
        external_id="REQ-NA",
        title="Requirement NA",
    )
    art_b = Artifact(
        project_id=None,
        type="requirement",
        source="internal",
        external_id="REQ-NB",
        title="Requirement NB",
    )
    db_session.add_all([art_a, art_b])
    await db_session.flush()
    a_id, b_id = art_a.id, art_b.id
    await db_session.commit()
    return a_id, b_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_link_null_tenant_does_not_duplicate(project_with_two_artifacts):
    """Two direct ``create_link`` calls (NULL tenant, same tuple) -> one row.

    The first call creates the link (count 1). The second call, with an
    identical (project, from, to, type) tuple and a NULL tenant_id, hits the
    tenant-agnostic existence check: it finds the committed row and raises
    ``ValueError("Link already exists")`` instead of inserting a second row, so
    the count stays 1. Before the fix the second call logged "Created link"
    again and the count became 2 (the NULL tenant defeated ``uq_artifact_link``).
    """
    project_id, a_id, b_id = project_with_two_artifacts

    # First direct call creates the link.
    await _create_link_via_service(a_id, b_id, project_id)
    assert await _link_count(project_id=project_id) == 1

    # Second call: identical (project, from, to, type) with NULL tenant. The
    # existence check short-circuits with a raise rather than inserting a dup.
    with pytest.raises(ValueError, match="Link already exists"):
        await _create_link_via_service(a_id, b_id, project_id)

    # The duplicate was NOT created — count is still exactly 1.
    assert await _link_count(project_id=project_id) == 1


@pytest.mark.asyncio
async def test_create_link_without_project_id_resolves_from_source_and_dedupes(
    project_with_two_artifacts,
):
    """Omitting project_id stores the link under the source artifact's project,
    and the dedup still holds.

    Exercises the ``effective_project_id = from_artifact.project_id`` fallback
    branch that the explicit-project test above never hits. The first call
    resolves the project from artifact A; the second (also without project_id)
    matches the same resolved tuple and raises, so the count stays 1.
    """
    project_id, a_id, b_id = project_with_two_artifacts

    # First call WITHOUT project_id -> resolves to the source artifact's project.
    await _create_link_via_service(a_id, b_id, None)
    links = await _all_links()
    assert len(links) == 1
    assert links[0].project_id == project_id  # resolved from from_artifact, not NULL

    # Second call, still without project_id: same resolved tuple -> dedup raise.
    with pytest.raises(ValueError, match="Link already exists"):
        await _create_link_via_service(a_id, b_id, None)
    assert await _link_count(project_id=project_id) == 1


@pytest.mark.asyncio
async def test_create_link_null_project_and_null_tenant_dedupes(two_artifacts_no_project):
    """Pure-NULL path: NULL project_id AND NULL tenant_id still dedupes.

    Both artifacts have a NULL project_id and project_id/tenant_id are omitted, so
    the stored link has ``project_id IS NULL`` and ``tenant_id IS NULL`` —
    ``uq_artifact_link`` provides zero coverage. Dedup rests entirely on the
    existence check's ``IS NULL`` comparisons: the 2nd call raises, count stays 1.
    """
    a_id, b_id = two_artifacts_no_project

    # First call: the stored link has NULL project_id and NULL tenant_id.
    await _create_link_via_service(a_id, b_id, None)
    links = await _all_links()
    assert len(links) == 1
    assert links[0].project_id is None
    assert links[0].tenant_id is None

    # Second identical call: dedup via the IS NULL comparisons -> raise.
    with pytest.raises(ValueError, match="Link already exists"):
        await _create_link_via_service(a_id, b_id, None)

    # Count ALL rows (can't filter on a NULL project_id); still exactly 1.
    assert await _link_count() == 1
