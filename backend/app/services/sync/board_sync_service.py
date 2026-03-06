"""Board and sprint synchronization service for Jira boards."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db_utils import supports_for_update
from app.models import Sprint, Task
from app.services.jira import JiraService
from app.utils import parse_datetime

logger = logging.getLogger(__name__)


@dataclass
class BoardSyncResult:
    """Result of board and sprint synchronization."""

    total_boards_processed: int = 0
    total_sprints_synced: int = 0
    total_tasks_linked: int = 0
    errors: List[tuple[str, str]] = field(default_factory=list)


class BoardSyncService:
    """
    Service responsible for synchronizing Jira boards and sprints.

    Handles:
    - Fetching boards for project
    - Syncing sprints from each board
    - Linking tasks to sprints based on Jira membership
    - Handling sprint metadata (dates, state, goal)
    """

    def __init__(self, jira_service: JiraService):
        self.jira_service = jira_service

    async def sync_boards(
        self,
        project_key: str,
        project_id: int,
        db: AsyncSession,
        heartbeat_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> BoardSyncResult:
        """
        Synchronize boards and sprints for a project.

        Args:
            project_key: Jira project key
            project_id: Internal project ID
            db: Database session

        Returns:
            BoardSyncResult with statistics and any errors
        """
        logger.info("Starting boards and sprints sync for project %s", project_key)

        result = BoardSyncResult()
        seen_sprint_ids: Set[str] = set()

        try:
            boards = self.jira_service.list_boards_for_project(project_key)
            logger.info("Boards for %s: %s", project_key, [board.get("name") for board in boards])

            for board in boards:
                board_name = board.get("name", "Unknown")
                try:
                    board_result = await self._sync_board_sprints(
                        board,
                        project_id,
                        db,
                        seen_sprint_ids=seen_sprint_ids,
                    )

                    result.total_boards_processed += 1
                    result.total_sprints_synced += board_result.total_sprints_synced
                    result.total_tasks_linked += board_result.total_tasks_linked
                    if heartbeat_callback is not None:
                        await heartbeat_callback(
                            {
                                "boards_processed": result.total_boards_processed,
                                "sprints_synced": result.total_sprints_synced,
                                "tasks_linked": result.total_tasks_linked,
                            }
                        )

                except Exception as e:
                    logger.error("Failed to sync board %s: %s", board_name, e, exc_info=True)
                    result.errors.append((board_name, str(e)))

            logger.info(
                "Completed boards and sprints sync for project %s: %d boards, %d sprints, %d tasks linked",
                project_key,
                result.total_boards_processed,
                result.total_sprints_synced,
                result.total_tasks_linked,
            )

        except Exception as e:
            logger.error("Boards and sprints sync failed for project %s: %s", project_key, e)
            result.errors.append(("sync_boards", str(e)))

        return result

    async def _sync_board_sprints(
        self,
        board: Dict[str, Any],
        project_id: int,
        db: AsyncSession,
        seen_sprint_ids: Set[str],
    ) -> BoardSyncResult:
        """
        Sync sprints from a single board.

        Returns:
            BoardSyncResult with sprint and task statistics
        """
        result = BoardSyncResult()
        board_id = board.get("id")

        if not board_id:
            return result

        try:
            sprints = await asyncio.to_thread(self.jira_service.list_sprints, board_id)

            for sprint in sprints:
                sprint_jira_id = sprint.get("id")
                sprint_key = str(sprint_jira_id) if sprint_jira_id is not None else ""
                if sprint_key and sprint_key in seen_sprint_ids:
                    continue
                if sprint_key:
                    seen_sprint_ids.add(sprint_key)
                try:
                    tasks_linked = await self._sync_sprint(
                        sprint,
                        project_id,
                        db,
                    )

                    result.total_sprints_synced += 1
                    result.total_tasks_linked += tasks_linked

                except Exception as e:
                    sprint_name = sprint.get("name", "Unknown")
                    logger.error("Failed to sync sprint %s: %s", sprint_name, e, exc_info=True)
                    result.errors.append((sprint_name, str(e)))

        except Exception as e:
            logger.error("Failed to fetch sprints for board %s: %s", board_id, e, exc_info=True)
            result.errors.append((f"board:{board_id}", str(e)))

        return result

    async def _sync_sprint(
        self,
        sprint: Dict[str, Any],
        project_id: int,
        db: AsyncSession,
    ) -> int:
        """
        Sync a single sprint and link its tasks.

        Returns:
            Number of tasks linked to the sprint
        """
        sprint_jira_id = sprint.get("id")
        if not sprint_jira_id:
            return 0

        # Fetch sprint issues outside DB transaction to avoid long-lived
        # open transactions while waiting on Jira network calls.
        sprint_issues = await asyncio.to_thread(
            self.jira_service.list_issues_in_sprint,
            sprint_jira_id,
        )
        issue_keys = [item.get("key") for item in sprint_issues if item.get("key")]

        async with db.begin():
            # Find or create sprint
            sel = select(Sprint).where(Sprint.jira_id == str(sprint_jira_id))
            if supports_for_update(db):
                sel = sel.with_for_update()

            db_sprint = (await db.execute(sel)).scalar_one_or_none()

            created_new = False
            if not db_sprint:
                db_sprint = Sprint(jira_id=str(sprint_jira_id))
                db.add(db_sprint)
                created_new = True

            # Update sprint fields
            name_val = sprint.get("name")
            db_sprint.name = str(name_val) if name_val is not None else "Unknown"
            db_sprint.goal = sprint.get("goal")
            db_sprint.state = sprint.get("state")
            db_sprint.project_id = project_id
            db_sprint.start_date = parse_datetime(sprint.get("startDate"))
            db_sprint.end_date = parse_datetime(sprint.get("endDate"))
            db_sprint.complete_date = parse_datetime(sprint.get("completeDate"))

            if created_new:
                # Ensure PK available for relation updates
                await db.flush()

            # Link tasks to sprint
            tasks_linked = await self._link_sprint_tasks(
                issue_keys,
                project_id,
                db_sprint.id,
                db,
            )

        return tasks_linked

    async def _link_sprint_tasks(
        self,
        issue_keys: List[str],
        project_id: int,
        sprint_db_id: int,
        db: AsyncSession,
    ) -> int:
        """
        Link tasks to sprint based on Jira sprint membership.

        Returns:
            Number of tasks linked
        """
        if not issue_keys:
            return 0

        # Find tasks by key and link to sprint
        tasks_query = select(Task).where(Task.key.in_(issue_keys), Task.project_id == project_id)

        tasks = (await db.execute(tasks_query)).scalars().all()
        tasks_linked = 0

        for task in tasks:
            task.sprint_id = sprint_db_id
            tasks_linked += 1

        return tasks_linked
