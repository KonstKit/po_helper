"""Corner case #10 (authorization half): bulk-approve must NOT mask an
authorization failure as a 200.

`test_suggestions_bulk_mixed.py` covers valid/duplicate/cycle/not-found, but the
default test user is a superuser so `ensure_project_access` always passes and the
`except HTTPException: raise` branch never runs. This module overrides the
current user with a NON-admin manager who cannot access the suggestion's project,
so `ensure_project_access` raises 403 and bulk-approve must surface it as a real
403 (not swallow it into an item-level error / 200).
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.traceability import Artifact, ArtifactLink, SuggestedLink


class _NonAdminManager:
    """Traceability manager who is NOT an admin/superuser and owns no project,
    so can_access_project() returns False for the seeded project."""

    id = 5150
    email = "manager@example.com"
    username = "manager"
    full_name = "Manager"
    is_active = True
    is_superuser = False
    mfa_enabled = False

    def has_permission(self, permission: str) -> bool:
        return permission in {"traceability:view", "traceability:manage"}

    def has_role(self, _role: str) -> bool:
        return False


@pytest_asyncio.fixture
async def suggestion_in_foreign_project(db_session):
    """A pending suggestion in a project the manager does not own/can't access."""
    project = Project(jira_key="SEC", name="Secured Project", owner_id=1)
    db_session.add(project)
    await db_session.flush()
    a = Artifact(
        project_id=project.id, type="requirement", source="internal",
        external_id="REQ-S1", title="S1",
    )
    b = Artifact(
        project_id=project.id, type="requirement", source="internal",
        external_id="REQ-S2", title="S2",
    )
    db_session.add_all([a, b])
    await db_session.flush()
    sug = SuggestedLink(
        project_id=project.id,
        from_artifact_id=a.id,
        to_artifact_id=b.id,
        suggested_link_type="relates_to",
        similarity_score=0.8,
        method="tfidf",
        reason="similar",
        status="pending",
    )
    db_session.add(sug)
    await db_session.commit()
    return project.id, sug.id


@pytest.mark.asyncio
async def test_bulk_approve_inaccessible_project_returns_403(
    client, auth_headers, suggestion_in_foreign_project
):
    from app.api.deps import get_current_user
    from app.main import app

    _project_id, sug_id = suggestion_in_foreign_project

    original = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: _NonAdminManager()
    try:
        resp = await client.post(
            "/api/v1/traceability/suggested-links/bulk-approve",
            json=[sug_id],
            headers=auth_headers,
        )
        # The authorization failure must surface as a real 403, NOT a 200 whose
        # body hides the failure in results.errors.
        assert resp.status_code == 403, resp.text
    finally:
        if original is not None:
            app.dependency_overrides[get_current_user] = original
        else:
            app.dependency_overrides.pop(get_current_user, None)

    # And nothing was approved / no link created behind the 403.
    async with AsyncSessionLocal() as s:
        status = (
            await s.execute(
                select(SuggestedLink.status).where(SuggestedLink.id == sug_id)
            )
        ).scalar_one()
        assert status == "pending"
        link_count = (
            await s.execute(select(func.count()).select_from(ArtifactLink))
        ).scalar()
        assert link_count == 0
