"""Issue synchronization service for Jira data import."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.utils import parse_datetime

logger = logging.getLogger(__name__)


@dataclass
class IssueSyncResult:
    """Result of issue synchronization operation."""

    total_processed: int = 0
    total_added: int = 0
    total_updated: int = 0
    total_saved: int = 0
    errors: List[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class IssueSyncService:
    """
    Service responsible for synchronizing Jira issues to the database.

    Handles:
    - Fetching issues from Jira
    - Batch processing for performance
    - Upserting issues to database
    - Maintaining issue lookup caches
    """

    BATCH_SIZE = 100  # Process 100 issues at a time

    def __init__(self):
        self._existing_task_ids_by_jira: Dict[str, int] = {}
        self._existing_task_ids_by_key: Dict[str, int] = {}

    async def sync_issues(
        self,
        project_key: str,
        project_id: int,
        issues: List[Dict[str, Any]],
        db: AsyncSession,
    ) -> IssueSyncResult:
        """
        Synchronize Jira issues to database with batching.

        Args:
            project_key: Jira project key
            project_id: Internal project ID
            issues: List of issue data from Jira API
            db: Database session

        Returns:
            IssueSyncResult with statistics and any errors
        """
        if not issues:
            logger.warning('No issues provided for sync for project %s', project_key)
            return IssueSyncResult()

        logger.info('Starting issue sync for project %s: %d issues', project_key, len(issues))

        # Build lookup cache for existing tasks
        await self._build_lookup_cache(project_id, db)

        result = IssueSyncResult()

        # Process in batches to avoid long database locks
        for batch_start in range(0, len(issues), self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, len(issues))
            batch = issues[batch_start:batch_end]

            # Progress logging
            if batch_start % 500 == 0 and batch_start > 0:
                logger.info(
                    'Saving issues for %s: %d/%d (%d%%)',
                    project_key,
                    batch_start,
                    len(issues),
                    int(batch_start / len(issues) * 100)
                )

            try:
                batch_result = await self._process_batch(
                    project_key,
                    project_id,
                    batch,
                    batch_start,
                    batch_end,
                    db,
                )

                result.total_added += batch_result.total_added
                result.total_updated += batch_result.total_updated
                result.total_saved += batch_result.total_saved
                result.total_processed += len(batch)

            except Exception as e:
                logger.error(
                    'Failed to process batch %d-%d for project %s: %s',
                    batch_start,
                    batch_end,
                    project_key,
                    e,
                    exc_info=True
                )
                result.errors.append((f"batch_{batch_start}_{batch_end}", str(e)))
                raise

        logger.info(
            'Completed issue sync for project %s: %d processed, %d added, %d updated',
            project_key,
            result.total_processed,
            result.total_added,
            result.total_updated
        )

        return result

    async def _build_lookup_cache(self, project_id: int, db: AsyncSession) -> None:
        """Build cache of existing task IDs for fast lookup."""
        result = await db.execute(
            select(Task.id, Task.jira_id, Task.key).where(Task.project_id == project_id)
        )

        for task_id, existing_jira_id, existing_key in result:
            if existing_jira_id:
                self._existing_task_ids_by_jira[str(existing_jira_id)] = task_id
            if existing_key:
                self._existing_task_ids_by_key[existing_key] = task_id

        logger.debug(
            'Built lookup cache: %d by jira_id, %d by key',
            len(self._existing_task_ids_by_jira),
            len(self._existing_task_ids_by_key)
        )

    async def _process_batch(
        self,
        project_key: str,
        project_id: int,
        batch: List[Dict[str, Any]],
        batch_start: int,
        batch_end: int,
        db: AsyncSession,
    ) -> IssueSyncResult:
        """Process a single batch of issues."""
        batch_result = IssueSyncResult()
        created_tasks: List[tuple[Task, Optional[str], Optional[str]]] = []

        for issue in batch:
            await self._process_single_issue(
                project_id,
                issue,
                db,
                batch_result,
                created_tasks,
            )

        # Commit batch
        await db.flush()

        # Update lookup cache with newly created tasks
        for created_task, created_jira_id, created_key in created_tasks:
            if created_jira_id:
                self._existing_task_ids_by_jira[str(created_jira_id)] = created_task.id
            if created_key:
                self._existing_task_ids_by_key[created_key] = created_task.id

        await db.commit()

        batch_result.total_saved = len(batch)

        logger.info(
            'Batch %d-%d committed: %d new, %d updated tasks for project %s',
            batch_start,
            batch_end,
            batch_result.total_added,
            batch_result.total_updated,
            project_key
        )

        # Verify the batch was actually saved
        await self._verify_batch(project_id, batch, db)

        return batch_result

    async def _process_single_issue(
        self,
        project_id: int,
        issue: Dict[str, Any],
        db: AsyncSession,
        batch_result: IssueSyncResult,
        created_tasks: List[tuple[Task, Optional[str], Optional[str]]],
    ) -> None:
        """Process a single issue - create or update in database."""
        fields = issue.get('fields', {}) if isinstance(issue, dict) else {}

        # Support both raw Jira shape (nested 'fields') and normalized (flat) shape
        is_raw = bool(fields)
        if not is_raw and isinstance(issue, dict):
            fields = issue  # treat as flat

        key = issue.get('key') if isinstance(issue, dict) else None
        jira_id_value = None
        if isinstance(issue, dict):
            jira_id_value = issue.get('id') or issue.get('jira_id')
        jira_id = str(jira_id_value) if jira_id_value is not None else None

        if not key and not jira_id:
            return

        # Find existing task
        db_issue = await self._find_existing_task(jira_id, key, db)

        if not db_issue:
            # Create new task
            db_issue = Task(project_id=project_id, key=key or jira_id, jira_id=jira_id)
            db.add(db_issue)
            batch_result.total_added += 1
            created_tasks.append((db_issue, jira_id, key))
        else:
            # Update existing task
            batch_result.total_updated += 1
            self._update_task_identifiers(db_issue, project_id, jira_id, key)

        # Update task fields
        self._update_task_fields(db_issue, fields, is_raw)

    async def _find_existing_task(
        self,
        jira_id: Optional[str],
        key: Optional[str],
        db: AsyncSession,
    ) -> Optional[Task]:
        """Find existing task by jira_id or key."""
        jira_lookup = str(jira_id) if jira_id else None
        task_id: Optional[int] = None

        if jira_lookup:
            task_id = self._existing_task_ids_by_jira.get(jira_lookup)
        if task_id is None and key:
            task_id = self._existing_task_ids_by_key.get(key)

        if task_id is not None:
            db_issue = await db.get(Task, task_id)
            if db_issue is None:
                # Cache is stale, clean it up
                if jira_id:
                    self._existing_task_ids_by_jira.pop(jira_lookup, None)
                if key:
                    self._existing_task_ids_by_key.pop(key, None)
            return db_issue

        return None

    def _update_task_identifiers(
        self,
        db_issue: Task,
        project_id: int,
        jira_id: Optional[str],
        key: Optional[str],
    ) -> None:
        """Update task identifiers (project_id, jira_id, key)."""
        if db_issue.project_id != project_id:
            db_issue.project_id = project_id

        if key and db_issue.key != key:
            if db_issue.key:
                self._existing_task_ids_by_key.pop(db_issue.key, None)
            db_issue.key = key

        if jira_id and db_issue.jira_id != jira_id:
            if db_issue.jira_id:
                self._existing_task_ids_by_jira.pop(str(db_issue.jira_id), None)
            db_issue.jira_id = jira_id

        # Update cache
        if jira_id:
            self._existing_task_ids_by_jira[str(jira_id)] = db_issue.id
        if key:
            self._existing_task_ids_by_key[key] = db_issue.id

    def _update_task_fields(
        self,
        db_issue: Task,
        fields: Dict[str, Any],
        is_raw: bool,
    ) -> None:
        """Update task fields from Jira data."""
        if not isinstance(fields, dict):
            return

        # Basic fields
        db_issue.summary = fields.get('summary')
        db_issue.description = fields.get('description')

        # Type, status, priority
        if is_raw:
            it = fields.get('issuetype')
            st = fields.get('status')
            pr = fields.get('priority')
            db_issue.task_type = self._extract_name(it)
            db_issue.status = self._extract_name(st) or db_issue.status or 'Unknown'
            db_issue.priority = self._extract_name(pr)
        else:
            db_issue.task_type = fields.get('task_type')
            db_issue.status = fields.get('status') or db_issue.status or 'Unknown'
            db_issue.priority = fields.get('priority')

        # Assignee and reporter
        self._update_people_fields(db_issue, fields, is_raw)

        # Time tracking
        self._update_time_fields(db_issue, fields, is_raw)

        # Dates
        self._update_date_fields(db_issue, fields, is_raw)

        # Labels and components
        db_issue.labels = fields.get('labels')
        self._update_components(db_issue, fields)

        # Custom fields (only for raw Jira data)
        if is_raw:
            db_issue.business_value = fields.get('customfield_business_value')
            db_issue.value_delivered = fields.get('customfield_value_delivered')
            db_issue.roi = fields.get('customfield_roi')
            db_issue.custom_fields = {
                k: v for k, v in fields.items()
                if isinstance(k, str) and k.startswith('customfield_')
            }

    def _extract_name(self, value: Any) -> Optional[str]:
        """Extract name from dict or return string value."""
        if isinstance(value, dict):
            return value.get('name')
        elif isinstance(value, str):
            return value
        return None

    def _update_people_fields(
        self,
        db_issue: Task,
        fields: Dict[str, Any],
        is_raw: bool,
    ) -> None:
        """Update assignee and reporter fields."""
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
            else:
                db_issue.assignee_email = None
                db_issue.assignee_name = None

            if isinstance(rep, dict):
                db_issue.reporter_email = rep.get('emailAddress')
                db_issue.reporter_name = rep.get('displayName')
            else:
                db_issue.reporter_email = None
                db_issue.reporter_name = None

    def _update_time_fields(
        self,
        db_issue: Task,
        fields: Dict[str, Any],
        is_raw: bool,
    ) -> None:
        """Update time tracking fields."""
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

    def _update_date_fields(
        self,
        db_issue: Task,
        fields: Dict[str, Any],
        is_raw: bool,
    ) -> None:
        """Update date fields."""
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

    def _update_components(self, db_issue: Task, fields: Dict[str, Any]) -> None:
        """Update components field."""
        components = fields.get('components')
        if isinstance(components, list):
            comp_names = []
            for c in components:
                if isinstance(c, dict) and c.get('name'):
                    comp_names.append(c.get('name'))
                elif isinstance(c, str):
                    comp_names.append(c)
            db_issue.components = comp_names

    async def _verify_batch(
        self,
        project_id: int,
        batch: List[Dict[str, Any]],
        db: AsyncSession,
    ) -> None:
        """Verify that batch was successfully saved to database."""
        keys = [i.get('key') for i in batch if i.get('key')]
        if not keys:
            return

        verify_query = select(func.count(Task.id)).where(
            Task.project_id == project_id,
            Task.key.in_(keys)
        )
        verify_result = await db.execute(verify_query)
        verify_count = verify_result.scalar()

        if verify_count != len(batch):
            logger.warning(
                'Verification failed: expected %d tasks, found %d in database',
                len(batch),
                verify_count
            )
