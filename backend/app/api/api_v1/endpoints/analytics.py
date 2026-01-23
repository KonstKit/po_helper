from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache_enhanced import (
    cached_endpoint,
    CacheTier,
    AnalyticsCacheKeys,
)

# Service-layer analytics queries
from app.services.analytics.velocity_service import (
    get_project_velocity as get_project_velocity_service,
)
from app.services.analytics.dora_service import (
    get_project_dora_metrics as get_project_dora_metrics_service,
)
from app.services.analytics.team_health_service import (
    get_project_team_health as get_project_team_health_service,
)
from app.services.analytics.budget_service import (
    get_project_budget_hours as get_project_budget_hours_service,
)
from app.services.analytics.quality_service import (
    get_sprint_quality as get_sprint_quality_service,
)
from app.services.analytics.risk_service import (
    get_project_risks as get_project_risks_service,
)
from app.services.analytics.forecast_service import (
    get_project_forecast as get_project_forecast_service,
    get_project_pr_forecast as get_project_pr_forecast_service,
)
from app.services.analytics.value_metrics_service import (
    get_project_value_metrics as get_project_value_metrics_service,
)
from app.services.analytics.test_trend_service import (
    get_test_trend as get_test_trend_service,
)
from app.services.analytics.coverage_trend_service import (
    get_coverage_trend as get_coverage_trend_service,
)
from app.services.analytics.wip_status_service import (
    get_sprint_wip_status as get_sprint_wip_status_service,
)
from app.services.analytics.capacity_service import (
    get_sprint_capacity as get_sprint_capacity_service,
)
from app.services.analytics.project_sprints_service import (
    get_project_sprints as get_project_sprints_service,
)
from app.services.analytics.sprint_burndown_service import (
    get_sprint_burndown as get_sprint_burndown_service,
)
from app.services.analytics.team_members_service import (
    get_team_members_activity as get_team_members_activity_service,
)
from app.services.analytics.project_burndown_service import (
    get_project_burndown as get_project_burndown_service,
)


router = APIRouter()


@router.get("/projects/{project_id}/velocity")
@cached_endpoint(
    key_builder=lambda project_id, sprints_count=5, **kw: AnalyticsCacheKeys.velocity(
        project_id, sprints_count
    ),
    tier=CacheTier.WARM,  # 5 min cache for velocity data
)
async def get_project_velocity(
    project_id: int,
    sprints_count: int = 5,
    db: AsyncSession = Depends(get_db),
):
    """Get project velocity metrics. Cached for 5 min."""
    return await get_project_velocity_service(
        db=db,
        project_id=project_id,
        sprints_count=sprints_count,
    )


@router.get("/projects/{project_id}/dora")
@cached_endpoint(
    key_builder=lambda project_id, window_days=30, **kw: AnalyticsCacheKeys.dora(
        project_id, window_days
    ),
    tier=CacheTier.WARM,  # 5 min cache for DORA metrics
)
async def get_dora_metrics(
    project_id: int,
    window_days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    return await get_project_dora_metrics_service(
        db=db,
        project_id=project_id,
        window_days=window_days,
    )


@router.get("/projects/{project_id}/budget-hours")
async def project_budget_hours(
    project_id: int,
    top_n: int = 5,
    db: AsyncSession = Depends(get_db),
):
    return await get_project_budget_hours_service(
        db=db,
        project_id=project_id,
        top_n=top_n,
    )


@router.get("/projects/{project_id}/value-metrics")
async def project_value_metrics(project_id: int, db: AsyncSession = Depends(get_db)):
    return await get_project_value_metrics_service(db=db, project_id=project_id)


@router.get("/sprints/{sprint_id}/wip-status")
async def sprint_wip_status(sprint_id: int, db: AsyncSession = Depends(get_db)):
    return await get_sprint_wip_status_service(db=db, sprint_id=sprint_id)


@router.get("/sprints/{sprint_id}/capacity")
async def sprint_capacity(sprint_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get capacity information for a sprint, using personalized capacity settings.

    This endpoint now looks up CapacitySettings for each assignee to get their
    individual hours_per_week and focus_factor, falling back to defaults (40h, 80%)
    if no custom settings exist.
    """
    return await get_sprint_capacity_service(db=db, sprint_id=sprint_id)


@router.get("/projects/{project_id}/sprints")
async def project_sprints(
    project_id: int,
    limit: int = Query(10, ge=1, le=100),
    board_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    return await get_project_sprints_service(
        db=db,
        project_id=project_id,
        limit=limit,
        board_id=board_id,
    )


@router.get("/sprints/{sprint_id}/burndown")
@cached_endpoint(
    key_builder=lambda sprint_id, **kw: AnalyticsCacheKeys.sprint_burndown(sprint_id),
    tier=CacheTier.HOT,  # 60 sec cache for burndown
)
async def sprint_burndown(sprint_id: int, db: AsyncSession = Depends(get_db)):
    """Get sprint burndown chart data. Cached for 60s."""
    return await get_sprint_burndown_service(db=db, sprint_id=sprint_id)


@router.get("/sprints/{sprint_id}/quality")
async def sprint_quality(sprint_id: int, db: AsyncSession = Depends(get_db)):
    return await get_sprint_quality_service(db=db, sprint_id=sprint_id)


@router.get("/projects/{project_id}/team-members")
async def get_team_members_activity(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get team members with their last activity dates"""
    return await get_team_members_activity_service(db=db, project_id=project_id)


@router.get("/projects/{project_id}/team-health")
@cached_endpoint(
    key_builder=lambda project_id, **kw: AnalyticsCacheKeys.team_health(project_id),
    tier=CacheTier.HOT,  # 60 sec cache for team health
)
async def get_project_team_health(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get team health metrics. Cached for 60s."""
    return await get_project_team_health_service(db=db, project_id=project_id)


@router.get("/projects/{project_id}/burndown")
@cached_endpoint(
    key_builder=lambda project_id, sprint_id=None, **kw: AnalyticsCacheKeys.project_burndown(
        project_id, sprint_id
    ),
    tier=CacheTier.HOT,  # 60 sec cache for project burndown
)
async def project_burndown(
    project_id: int,
    sprint_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get project burndown chart. Cached for 60s."""
    return await get_project_burndown_service(
        db=db,
        project_id=project_id,
        sprint_id=sprint_id,
    )


@router.get("/projects/{project_id}/risks")
@cached_endpoint(
    key_builder=lambda project_id, **kw: AnalyticsCacheKeys.project_risks(project_id),
    tier=CacheTier.WARM,  # 5 min cache for risk analysis
)
async def identify_project_risks(project_id: int, db: AsyncSession = Depends(get_db)):
    return await get_project_risks_service(db=db, project_id=project_id)


@router.get("/projects/{project_id}/forecast")
@cached_endpoint(
    key_builder=lambda project_id, **kw: AnalyticsCacheKeys.project_forecast(project_id),
    tier=CacheTier.WARM,  # 5 min cache for forecast
)
async def forecast_completion(project_id: int, db: AsyncSession = Depends(get_db)):
    return await get_project_forecast_service(db=db, project_id=project_id)


@router.get("/test-trend")
@cached_endpoint(
    key_builder=lambda project_id=None, days=14, **kw: AnalyticsCacheKeys.test_trend(
        project_id, days
    ),
    tier=CacheTier.WARM,  # 5 min cache for test trends
)
async def test_trend(
    project_id: Optional[int] = Query(None),
    days: int = Query(14, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
):
    return await get_test_trend_service(db=db, days=days, project_id=project_id)


@router.get("/coverage-trend")
@cached_endpoint(
    key_builder=lambda project_id=None, days=30, **kw: AnalyticsCacheKeys.coverage_trend(
        project_id, days
    ),
    tier=CacheTier.COLD,  # 15 min cache for coverage trends
)
async def coverage_trend(
    project_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    return await get_coverage_trend_service(db=db, days=days, project_id=project_id)


@router.get("/projects/{project_id}/forecast/pr")
async def project_pr_forecast(project_id: int, db: AsyncSession = Depends(get_db)):
    return await get_project_pr_forecast_service(db=db, project_id=project_id)
