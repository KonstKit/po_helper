from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PullRequest, Task
from app.services.analytics_utils import calculate_dora_metrics

logger = logging.getLogger(__name__)


async def get_project_dora_metrics(
    db: AsyncSession,
    project_id: int,
    window_days: int = 30,
) -> Dict[str, Any]:
    """Compute DORA metrics for a project over a time window."""
    window_days = max(1, int(window_days or 30))
    since = datetime.utcnow() - timedelta(days=window_days)
    now_utc = datetime.utcnow()

    logger.info("analytics.dora.start project_id=%s window=%s", project_id, window_days)

    task_key_rows = await db.execute(select(Task.key).where(Task.project_id == project_id))
    task_keys = {str(row[0]).upper() for row in task_key_rows.all() if row[0]}
    if not task_keys:
        logger.info("analytics.dora.no_tasks project_id=%s", project_id)
        metrics = calculate_dora_metrics([], [], window_days)
        metrics["timeframe"] = {"start": since.isoformat(), "end": now_utc.isoformat()}
        return metrics

    from app.models import ProjectRepository

    repo_ids_stmt = select(ProjectRepository.repository_id).where(
        ProjectRepository.project_id == project_id
    )
    repo_ids = list((await db.execute(repo_ids_stmt)).scalars().all())

    if repo_ids:
        pr_stmt = (
            select(PullRequest)
            .where(PullRequest.repository_id.in_(repo_ids))
            .where(PullRequest.merged_at.is_not(None))
            .where(PullRequest.merged_at >= since)
        )
    else:
        pr_stmt = (
            select(PullRequest)
            .where(PullRequest.merged_at.is_not(None))
            .where(PullRequest.merged_at >= since)
        )

    deployments: List[PullRequest] = []
    for pr in (await db.execute(pr_stmt)).scalars().all():
        keys = {str(key).upper() for key in (pr.jira_keys or []) if isinstance(key, str)}
        if keys and keys & task_keys:
            deployments.append(pr)

    incident_stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        .where(Task.task_type.is_not(None))
        .where(func.lower(Task.task_type).like("%incident%"))
        .where(or_(Task.created_date >= since, Task.resolved_date >= since))
    )
    incidents: List[Task] = list((await db.execute(incident_stmt)).scalars().all())

    metrics = calculate_dora_metrics(deployments, incidents, window_days)
    metrics["timeframe"] = {"start": since.isoformat(), "end": now_utc.isoformat()}
    metrics["totals"].update({"deployments_considered": len(deployments)})
    logger.info(
        "analytics.dora.success project_id=%s deployments=%s incidents=%s",
        project_id,
        len(deployments),
        len(incidents),
    )
    return metrics
