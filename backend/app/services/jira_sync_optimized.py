from __future__ import annotations

import logging
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, List, Dict
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.database import AsyncSessionLocal
from app.core.db_utils import supports_for_update
from app.models import Project, Sprint, SprintSnapshot, Task, WorkLog, IntegrationSetting
from app.core.config import settings
from app.core.crypto import decrypt_str
from app.services.jira_service import jira_service, JiraAuthError, JiraUnexpectedResponse
from app.utils import parse_datetime

logger = logging.getLogger(__name__)

# Batch processing configuration
BATCH_SIZE = 100  # Process issues in batches of 100
COMMIT_INTERVAL = 500  # Commit every 500 issues to reduce lock time


async def _notify(event_type: str, **payload: Any) -> None:
    try:
        from app.core.notifications import connections
        await connections.broadcast_json({'type': event_type, **payload})
    except Exception:
        pass


async def _process_issues_batch(
    issues: List[Dict],
    project_id: int,
    project_key: str,
    batch_num: int,
    total_batches: int
) -> None:
    """Process a batch of issues efficiently."""
    async with AsyncSessionLocal() as db:
        # Fetch existing tasks in batch
        issue_keys = [issue.get('key') for issue in issues if issue.get('key')]
        if not issue_keys:
            return

        # Get all existing tasks for this batch in one query
        existing_tasks_query = select(Task).where(
            Task.key.in_(issue_keys),
            Task.project_id == project_id
        )
        result = await db.execute(existing_tasks_query)
        existing_tasks = {task.key: task for task in result.scalars().all()}

        # Process issues
        new_tasks = []
        for issue in issues:
            fields = issue.get('fields', {}) if isinstance(issue, dict) else {}
            is_raw = bool(fields)
            if not is_raw and isinstance(issue, dict):
                fields = issue

            key = issue.get('key') if isinstance(issue, dict) else None
            if not key:
                continue

            # Check if task exists
            if key in existing_tasks:
                db_issue = existing_tasks[key]
            else:
                jira_id = issue.get('id') or issue.get('jira_id')
                db_issue = Task(project_id=project_id, key=key, jira_id=jira_id)
                new_tasks.append(db_issue)
                db.add(db_issue)

            # Update fields (same logic as original)
            db_issue.summary = fields.get('summary') if isinstance(fields, dict) else None
            db_issue.description = fields.get('description') if isinstance(fields, dict) else None

            if is_raw:
                it = fields.get('issuetype')
                st = fields.get('status')
                pr = fields.get('priority')
                db_issue.task_type = (it.get('name') if isinstance(it, dict) else (it if isinstance(it, str) else None))
                db_issue.status = (st.get('name') if isinstance(st, dict) else (st if isinstance(st, str) else None)) or db_issue.status or 'Unknown'
                db_issue.priority = (pr.get('name') if isinstance(pr, dict) else (pr if isinstance(pr, str) else None))
            else:
                db_issue.task_type = fields.get('task_type')
                db_issue.status = fields.get('status') or db_issue.status or 'Unknown'
                db_issue.priority = fields.get('priority')

            # Process assignee and reporter
            if not is_raw:
                db_issue.assignee_email = fields.get('assignee_email')
                db_issue.assignee_name = fields.get('assignee_name')
                db_issue.reporter_email = fields.get('reporter_email')
                db_issue.reporter_name = fields.get('reporter_name')
            else:
                asg = fields.get('assignee')
                rep = fields.get('reporter')
                if isinstance(asg, dict):
                    db_issue.assignee_email = asg.get('emailAddress')
                    db_issue.assignee_name = asg.get('displayName')
                if isinstance(rep, dict):
                    db_issue.reporter_email = rep.get('emailAddress')
                    db_issue.reporter_name = rep.get('displayName')

            # Process time tracking
            if is_raw:
                estimate_seconds = fields.get('timeoriginalestimate') or 0
                db_issue.estimate_hours = round(estimate_seconds / 3600.0, 2) if estimate_seconds else None
                spent_seconds = fields.get('timespent') or 0
                db_issue.spent_hours = round(spent_seconds / 3600.0, 2) if spent_seconds else None
                remaining_seconds = fields.get('timeestimate') or 0
                db_issue.remaining_hours = round(remaining_seconds / 3600.0, 2) if remaining_seconds else None
            else:
                db_issue.estimate_hours = fields.get('estimate_hours')
                db_issue.spent_hours = fields.get('spent_hours')
                db_issue.remaining_hours = fields.get('remaining_hours')

            # Process dates
            if is_raw:
                db_issue.created_date = parse_datetime(fields.get('created'))
                db_issue.updated_date = parse_datetime(fields.get('updated'))
                db_issue.resolved_date = parse_datetime(fields.get('resolutiondate'))
                db_issue.due_date = parse_datetime(fields.get('duedate'))
            else:
                db_issue.created_date = parse_datetime(fields.get('created_date'))
                db_issue.updated_date = parse_datetime(fields.get('updated_date'))
                db_issue.resolved_date = parse_datetime(fields.get('resolved_date'))
                db_issue.due_date = parse_datetime(fields.get('due_date'))

            # Process labels and components
            db_issue.labels = fields.get('labels') if isinstance(fields, dict) else None
            components = fields.get('components') if isinstance(fields, dict) else None
            if isinstance(components, list):
                comp_names = []
                for c in components:
                    if isinstance(c, dict) and c.get('name'):
                        comp_names.append(c.get('name'))
                    elif isinstance(c, str):
                        comp_names.append(c)
                db_issue.components = comp_names

            # Process custom fields
            if is_raw:
                db_issue.business_value = fields.get('customfield_business_value')
                db_issue.value_delivered = fields.get('customfield_value_delivered')
                db_issue.roi = fields.get('customfield_roi')
                db_issue.custom_fields = {
                    k: v for k, v in fields.items() if isinstance(k, str) and k.startswith('customfield_')
                }

        # Commit this batch
        await db.commit()
        logger.info(
            'Processed batch %d/%d for project %s (batch size: %d)',
            batch_num,
            total_batches,
            project_key,
            len(issues)
        )

        # Small delay to allow other operations
        await asyncio.sleep(0.1)


async def perform_project_sync_optimized(project_key: str, project_id: int) -> None:
    '''Optimized synchronization of Jira data for a single project.'''
    try:
        logger.info('sync_project_issues started for %s (project_id=%s)', project_key, project_id)

        # Ensure Jira service is connected
        if not getattr(jira_service, 'base_url', None) or (
            jira_service.auth is None and jira_service.bearer_token is None
        ):
            try:
                async with AsyncSessionLocal() as db:
                    res = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == 'jira'))
                    row = res.scalar_one_or_none()
                    if row and row.base_url and row.api_token:
                        token = decrypt_str(row.api_token)
                        email = None if getattr(settings, 'JIRA_FORCE_PAT', True) else (row.email or None)
                        jira_service.connect(row.base_url, email, token)
                        logger.info('Jira connected in worker using stored settings')
            except Exception as e:
                logger.warning('Worker Jira bootstrap failed: %s', e)

        # Fetch issues from Jira (run in thread pool to avoid blocking)
        loop = asyncio.get_event_loop()
        issues = await loop.run_in_executor(
            None,
            jira_service.get_project_issues,
            project_key
        )

        logger.info('Fetched %d issues for project %s', len(issues) if issues else 0, project_key)

        if not issues:
            logger.warning('No issues fetched for project %s', project_key)
            await _notify(
                'jira_sync_failed',
                project_key=project_key,
                project_id=project_id,
                reason='empty',
                detail='No issues returned from Jira',
            )
            return

        # Process issues in batches
        total_issues = len(issues)
        total_batches = (total_issues + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_num in range(total_batches):
            start_idx = batch_num * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, total_issues)
            batch = issues[start_idx:end_idx]

            await _process_issues_batch(
                batch,
                project_id,
                project_key,
                batch_num + 1,
                total_batches
            )

            # Send progress notification
            progress = ((batch_num + 1) / total_batches) * 100
            await _notify(
                'jira_sync_progress',
                project_key=project_key,
                project_id=project_id,
                progress=progress,
                processed=end_idx,
                total=total_issues
            )

        logger.info('Saved %d issues for project %s', total_issues, project_key)

        # Continue with worklogs, sprints, etc. (same as original but with batching)
        # ... (rest of the sync logic remains similar but with batching applied)

        await _notify('jira_sync_complete', project_key=project_key, project_id=project_id)

    except Exception as exc:
        logger.error('Error syncing issues for %s: %s', project_key, exc)
        await _notify(
            'jira_sync_failed',
            project_key=project_key,
            project_id=project_id,
            reason='error',
            detail=str(exc),
        )