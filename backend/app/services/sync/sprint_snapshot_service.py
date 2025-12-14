"""Sprint snapshot service for historical sprint data generation."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Sprint, SprintSnapshot, Task, WorkLog

logger = logging.getLogger(__name__)


@dataclass
class SnapshotResult:
    """Result of sprint snapshot generation."""

    total_sprints_processed: int = 0
    total_snapshots_created: int = 0
    sprints_skipped: int = 0
    errors: List[tuple[str, str]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class SprintSnapshotService:
    """
    Service responsible for generating historical sprint snapshots.

    Handles:
    - Creating daily snapshots for each sprint
    - Calculating commitment (initial estimates)
    - Tracking cumulative work spent
    - Recording scope changes
    - Burndown chart data generation
    """

    async def create_snapshots(
        self,
        project_id: int,
        db: AsyncSession,
    ) -> SnapshotResult:
        """
        Create historical snapshots for all project sprints.

        Args:
            project_id: Internal project ID
            db: Database session

        Returns:
            SnapshotResult with statistics and any errors
        """
        logger.info('Starting sprint snapshots generation for project %d', project_id)

        result = SnapshotResult()

        # Fetch all sprints for the project
        sprint_rows = await db.execute(
            select(Sprint).where(Sprint.project_id == project_id)
        )
        sprints = sprint_rows.scalars().all()

        if not sprints:
            logger.info('No sprints found for project %d', project_id)
            return result

        for sprint in sprints:
            try:
                if not sprint.start_date or not (sprint.end_date or sprint.complete_date):
                    result.sprints_skipped += 1
                    continue

                snapshots_created = await self._create_sprint_snapshots(
                    sprint,
                    project_id,
                    db,
                )

                result.total_sprints_processed += 1
                result.total_snapshots_created += snapshots_created

            except Exception as e:
                logger.error(
                    'Failed to create snapshots for sprint %s: %s',
                    sprint.name,
                    e,
                    exc_info=True
                )
                result.errors.append((sprint.name or str(sprint.id), str(e)))

        await db.commit()

        logger.info(
            'Completed sprint snapshots for project %d: %d sprints, %d snapshots, %d skipped',
            project_id,
            result.total_sprints_processed,
            result.total_snapshots_created,
            result.sprints_skipped
        )

        return result

    async def _create_sprint_snapshots(
        self,
        sprint: Sprint,
        project_id: int,
        db: AsyncSession,
    ) -> int:
        """
        Create daily snapshots for a single sprint.

        Returns:
            Number of snapshots created
        """
        start = sprint.start_date
        end = sprint.end_date or sprint.complete_date

        # Delete existing snapshots
        existing = await db.execute(
            select(SprintSnapshot).where(SprintSnapshot.sprint_id == sprint.id)
        )
        for row in existing.scalars().all():
            await db.delete(row)

        # Fetch sprint tasks
        task_rows = await db.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.sprint_id == sprint.id
            )
        )
        sprint_tasks = task_rows.scalars().all()

        # Calculate initial commitment (tasks present at sprint start)
        commitment = sum(
            (task.estimate_hours or 0.0)
            for task in sprint_tasks
            if not task.created_date or task.created_date <= start
        )

        # Aggregate work spent per day
        spent_per_day = await self._calculate_daily_work(
            sprint_tasks,
            start,
            end,
            db,
        )

        # Create daily snapshots
        snapshots_created = await self._generate_daily_snapshots(
            sprint,
            sprint_tasks,
            start,
            end,
            commitment,
            spent_per_day,
            db,
        )

        return snapshots_created

    async def _calculate_daily_work(
        self,
        sprint_tasks: List[Task],
        start: datetime,
        end: datetime,
        db: AsyncSession,
    ) -> Dict[Any, float]:
        """
        Calculate work spent per day from worklogs.

        Returns:
            Dict mapping day (date) to hours spent
        """
        spent_per_day: defaultdict[Any, float] = defaultdict(float)

        if not sprint_tasks:
            return spent_per_day

        task_ids = [task.id for task in sprint_tasks]

        query = (
            select(
                func.date(WorkLog.started).label('day'),
                func.coalesce(
                    func.sum(WorkLog.time_spent_seconds / 3600.0),
                    0.0
                ).label('hours'),
            )
            .where(
                WorkLog.task_id.in_(task_ids),
                WorkLog.started.is_not(None),
                func.date(WorkLog.started) >= start.date(),
                func.date(WorkLog.started) <= end.date(),
            )
            .group_by('day')
        )

        result = await db.execute(query)

        for day_value, hours in result.all():
            spent_per_day[day_value] = float(hours or 0.0)

        return spent_per_day

    async def _generate_daily_snapshots(
        self,
        sprint: Sprint,
        sprint_tasks: List[Task],
        start: datetime,
        end: datetime,
        commitment: float,
        spent_per_day: Dict[Any, float],
        db: AsyncSession,
    ) -> int:
        """
        Generate daily snapshot records for the sprint.

        Returns:
            Number of snapshots created
        """
        cumulative = 0.0
        total_days = (end.date() - start.date()).days or 1
        snapshots_created = 0

        for offset in range(total_days + 1):
            day = start.date() + timedelta(days=offset)

            # Add daily spend to cumulative
            daily_spent = spent_per_day.get(day, 0.0)
            cumulative += daily_spent

            # Calculate remaining work
            remaining = max(commitment - cumulative, 0.0)

            # Calculate scope added this day
            scope_added = sum(
                (task.estimate_hours or 0.0)
                for task in sprint_tasks
                if task.created_date
                and task.created_date.date() == day
                and task.created_date > start
            )

            # Create snapshot
            snapshot = SprintSnapshot(
                sprint_id=sprint.id,
                date=datetime.combine(day, datetime.min.time(), tzinfo=start.tzinfo),
                total_estimate_hours=commitment,
                remaining_hours=remaining,
                completed_hours=min(cumulative, commitment),
                scope_added_hours=scope_added,
            )

            db.add(snapshot)
            snapshots_created += 1

        return snapshots_created
