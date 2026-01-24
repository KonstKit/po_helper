from __future__ import annotations

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.testrail.sync import DEFAULT_LOOKBACK_DAYS, TestRailSyncResult, TestRailSyncService


class TestRailSyncOrchestrator:
    """Coordinates TestRail sync using the configured client."""

    async def sync_project(
        self,
        db: AsyncSession,
        *,
        project_id: Optional[int],
        testrail_project_id: Optional[int] = None,
        suite_ids: Optional[List[int]] = None,
        cursor: Optional[int] = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        trigger: Optional[str] = "manual",
    ) -> TestRailSyncResult:
        service, _ = await TestRailSyncService.from_settings(db, project_id)
        try:
            return await service.sync_project(
                db,
                project_id=project_id,
                testrail_project_id=testrail_project_id,
                suite_ids=suite_ids,
                cursor=cursor,
                lookback_days=lookback_days,
                trigger=trigger,
            )
        finally:
            service.client.close()
