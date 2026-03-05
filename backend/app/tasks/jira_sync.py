from __future__ import annotations

import logging

from app.core.celery_async_runner import run_async
from app.core.celery_app import celery_app
from app.services.jira_sync import perform_project_sync

logger = logging.getLogger(__name__)


@celery_app.task(name="jira.sync_project_issues")
def sync_project_issues_task(project_key: str, project_id: int) -> None:
    """Trigger the asynchronous Jira sync via Celery."""
    logger.info("Celery task started for project %s (id=%s)", project_key, project_id)
    run_async(perform_project_sync(project_key, project_id))
