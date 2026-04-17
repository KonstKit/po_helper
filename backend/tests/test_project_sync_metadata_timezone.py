from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import Project
from app.services.sync.project_sync_orchestrator import ProjectSyncOrchestrator


@pytest.mark.asyncio
async def test_update_project_metadata_serializes_last_sync_at_with_timezone_offset(db_session):
    project = Project(jira_key="TZSYNC", name="Timezone Sync Project", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    orchestrator = ProjectSyncOrchestrator()
    await orchestrator._update_project_metadata(project.id, issues=[{"id": "1"}])

    db_session.expire_all()
    await db_session.refresh(project)
    refreshed = project
    assert refreshed.meta is not None

    last_sync_at = refreshed.meta.get("last_sync_at")
    assert isinstance(last_sync_at, str)
    assert last_sync_at.endswith("+00:00")

    parsed = datetime.fromisoformat(last_sync_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(parsed)
