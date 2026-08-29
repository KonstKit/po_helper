"""
Celery tasks for scheduled Git polling sync.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.core.celery_async_runner import run_async
from app.core.celery_app import TASK_RETRY_KWARGS, celery_app
from app.core.database import AsyncSessionLocal
from app.models import ProjectRepository
from app.services.git_import_service import git_import_service

logger = logging.getLogger(__name__)


@celery_app.task(name="git.scheduled_sync", **TASK_RETRY_KWARGS)
def scheduled_git_sync() -> dict[str, Any]:
    """Scheduled task to sync Git commits/PRs for all linked projects."""
    logger.info("Running scheduled Git sync")

    async def _run() -> list[dict[str, Any]]:
        async with AsyncSessionLocal() as db:
            project_rows = await db.execute(select(ProjectRepository.project_id).distinct())
            project_ids = [row[0] for row in project_rows.fetchall()]

        results: list[dict[str, Any]] = []
        for project_id in project_ids:
            async with AsyncSessionLocal() as db:
                sync_result = await git_import_service.sync_project(
                    db,
                    project_id,
                    include_commits=True,
                    include_pull_requests=True,
                    trigger="schedule",
                )
                results.append(sync_result)
        return results

    results: list[dict[str, Any]] = []
    try:
        results = run_async(_run())
    except Exception as exc:
        logger.error("Scheduled Git sync failed: %s", exc)
        return {"status": "error", "message": str(exc), "projects": 0, "repositories": 0}

    project_count = len(results)
    repo_count = sum(len(result.get("repositories", [])) for result in results)

    logger.info("Scheduled Git sync complete: %d project(s), %d repos", project_count, repo_count)
    return {"status": "ok", "projects": project_count, "repositories": repo_count}
