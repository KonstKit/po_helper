from __future__ import annotations

import logging

from app.services.sync import ProjectSyncOrchestrator

logger = logging.getLogger(__name__)


async def perform_project_sync(
    project_key: str, project_id: int, trigger: str | None = "manual"
) -> None:
    """
    Synchronise Jira data for a single project.

    Refactored to use ProjectSyncOrchestrator which coordinates:
    - Issue synchronization (IssueSyncService)
    - Worklog import (WorklogSyncService)
    - Sprint snapshots (SprintSnapshotService)
    - Board/sprint mapping (BoardSyncService)
    - Project metadata updates

    Each service can fail independently without affecting others.
    """
    orchestrator = ProjectSyncOrchestrator()
    result = await orchestrator.sync_project(project_key, project_id, trigger=trigger)

    # Log comprehensive result
    if result.success:
        logger.info(
            "Project sync succeeded for %s: %d issues, %.2fs duration",
            project_key,
            result.total_issues,
            result.sync_duration_seconds,
        )
    else:
        logger.error(
            "Project sync failed for %s: reason=%s, errors=%d",
            project_key,
            result.failure_reason,
            len(result.errors),
        )
