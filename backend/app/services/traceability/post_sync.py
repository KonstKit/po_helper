from __future__ import annotations

import logging
from typing import Optional

from app.core.cache_enhanced import CacheInvalidator
from app.core.config import settings

logger = logging.getLogger(__name__)


async def run_traceability_post_sync(
    project_id: Optional[int],
    *,
    artifact_delta: int,
    source: str,
    trigger: Optional[str] = None,
) -> None:
    if project_id is None or artifact_delta <= 0:
        return

    await CacheInvalidator.on_artifact_link_change(project_id)

    from app.tasks.traceability_tasks import (
        _execute_sync_complete_rules_async,
        _generate_suggestions_async,
        execute_sync_complete_rules_task,
        generate_suggestions_task,
    )

    if settings.CELERY_ENABLED:
        try:
            generate_suggestions_task.delay(project_id)
        except Exception as exc:
            logger.warning(
                "Failed to dispatch traceability suggestions task for project %s: %s",
                project_id,
                exc,
            )

        try:
            execute_sync_complete_rules_task.delay(
                project_id=project_id, source=source, trigger=trigger
            )
        except Exception as exc:
            logger.warning(
                "Failed to dispatch traceability sync-complete rules for project %s: %s",
                project_id,
                exc,
            )
        return

    try:
        await _generate_suggestions_async(project_id)
    except Exception as exc:
        logger.warning(
            "Inline traceability suggestion generation failed for project %s: %s",
            project_id,
            exc,
        )

    try:
        await _execute_sync_complete_rules_async(project_id, source=source, trigger=trigger)
    except Exception as exc:
        logger.warning(
            "Inline sync-complete rule execution failed for project %s: %s",
            project_id,
            exc,
        )
