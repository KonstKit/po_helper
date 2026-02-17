"""
Capacity Settings API endpoints.

Provides CRUD operations for personalized team capacity settings,
team health checks, and CFD snapshot management.
"""

from typing import Optional, Dict, Any
from datetime import date
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache_enhanced import (
    cached_endpoint,
    CacheTier,
    CapacityCacheKeys,
)
from app.utils.error_handling import handle_api_error, async_handle_api_error
from app.schemas.pagination import paginated_response
from app.models.capacity import CapacitySettings, TeamHealthCheck, CFDSnapshot
from app.models.task import Task
from app.schemas.capacity import (
    CapacitySettingsCreate,
    CapacitySettingsUpdate,
    CapacitySettings as CapacitySettingsSchema,
    TeamCapacitySummary,
    TeamHealthCheckCreate,
    TeamHealthCheck as TeamHealthCheckSchema,
    TeamHealthSummary,
    HealthTrend,
    CFDSnapshot as CFDSnapshotSchema,
    CFDData,
    FlowMetrics,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# =============================================================================
# Capacity Settings Endpoints
# =============================================================================


@router.get("/settings")
async def list_capacity_settings(
    project_id: Optional[int] = None,
    assignee_email: Optional[str] = None,
    include_expired: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    List capacity settings with optional filtering.

    Returns paginated response with metadata.

    - **project_id**: Filter by project (None = global settings)
    - **assignee_email**: Filter by specific assignee
    - **include_expired**: Include settings past their valid_to date
    """
    with handle_api_error(operation="list_capacity_settings"):
        # Build base filter conditions
        conditions = []
        if project_id is not None:
            conditions.append(CapacitySettings.project_id == project_id)
        if assignee_email:
            conditions.append(CapacitySettings.assignee_email == assignee_email)
        if not include_expired:
            today = date.today()
            conditions.append(
                or_(CapacitySettings.valid_to.is_(None), CapacitySettings.valid_to >= today)
            )

        # Build queries
        base_query = select(CapacitySettings)
        if conditions:
            base_query = base_query.where(and_(*conditions))

        count_query = select(func.count()).select_from(base_query.subquery())
        data_query = base_query.order_by(CapacitySettings.assignee_email).offset(skip).limit(limit)

        # AsyncSession does not support concurrent operations on the same session.
        count_result = await db.execute(count_query)
        data_result = await db.execute(data_query)

        total = count_result.scalar() or 0
        settings = data_result.scalars().all()

        return paginated_response(
            data=[CapacitySettingsSchema.from_orm_with_effective(s).model_dump() for s in settings],
            total=total,
            skip=skip,
            limit=limit,
        )


@router.get("/settings/{setting_id}", response_model=CapacitySettingsSchema)
async def get_capacity_setting(
    setting_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific capacity setting by ID."""
    with handle_api_error(operation="get_capacity_setting", context={"setting_id": setting_id}):
        result = await db.execute(select(CapacitySettings).where(CapacitySettings.id == setting_id))
        setting = result.scalar_one_or_none()

        if not setting:
            raise HTTPException(status_code=404, detail="Capacity setting not found")

        return CapacitySettingsSchema.from_orm_with_effective(setting)


@router.post("/settings", response_model=CapacitySettingsSchema)
async def create_capacity_setting(
    data: CapacitySettingsCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new capacity setting for a team member.

    Focus factor represents the percentage of theoretical capacity that's
    actually productive (typically 70-85% due to meetings, interruptions).
    """
    async with async_handle_api_error(
        operation="create_capacity_setting",
        context={"assignee_email": data.assignee_email},
        db_session=db,
    ):
        # Check for existing active setting for this assignee/project combo
        existing_query = select(CapacitySettings).where(
            and_(
                CapacitySettings.assignee_email == data.assignee_email,
                CapacitySettings.project_id == data.project_id,
                or_(CapacitySettings.valid_to.is_(None), CapacitySettings.valid_to >= date.today()),
            )
        )
        existing = (await db.execute(existing_query)).scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Active capacity setting already exists for {data.assignee_email}",
            )

        setting = CapacitySettings(
            project_id=data.project_id,
            assignee_email=data.assignee_email,
            assignee_name=data.assignee_name,
            hours_per_week=data.hours_per_week,
            focus_factor=data.focus_factor,
            valid_from=data.valid_from,
            valid_to=data.valid_to,
            notes=data.notes,
        )

        db.add(setting)
        await db.commit()
        await db.refresh(setting)

        logger.info(
            "Created capacity setting for %s: %sh/week @ %.0f%% focus",
            data.assignee_email,
            data.hours_per_week,
            data.focus_factor * 100,
        )

        return CapacitySettingsSchema.from_orm_with_effective(setting)


@router.put("/settings/{setting_id}", response_model=CapacitySettingsSchema)
async def update_capacity_setting(
    setting_id: int,
    data: CapacitySettingsUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing capacity setting."""
    async with async_handle_api_error(
        operation="update_capacity_setting", context={"setting_id": setting_id}, db_session=db
    ):
        result = await db.execute(select(CapacitySettings).where(CapacitySettings.id == setting_id))
        setting = result.scalar_one_or_none()

        if not setting:
            raise HTTPException(status_code=404, detail="Capacity setting not found")

        # Update only provided fields
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(setting, field, value)

        await db.commit()
        await db.refresh(setting)

        return CapacitySettingsSchema.from_orm_with_effective(setting)


@router.delete("/settings/{setting_id}")
async def delete_capacity_setting(
    setting_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a capacity setting."""
    async with async_handle_api_error(
        operation="delete_capacity_setting", context={"setting_id": setting_id}, db_session=db
    ):
        result = await db.execute(select(CapacitySettings).where(CapacitySettings.id == setting_id))
        setting = result.scalar_one_or_none()

        if not setting:
            raise HTTPException(status_code=404, detail="Capacity setting not found")

        await db.delete(setting)
        await db.commit()

        return {"status": "deleted", "id": setting_id}


@router.get("/team-summary/{project_id}", response_model=TeamCapacitySummary)
@cached_endpoint(
    key_builder=lambda project_id, **kw: CapacityCacheKeys.team_summary(project_id),
    tier=CacheTier.HOT,  # 60 sec cache for capacity data
)
async def get_team_capacity_summary(
    project_id: int,
    sprint_weeks: float = Query(2.0, ge=0.5, le=8.0),
    reference_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get aggregated capacity summary for a team. Cached for 60 seconds.

    - **sprint_weeks**: Duration of sprint in weeks for capacity calculation
    - **reference_date**: Date to check validity of settings (defaults to today)
    """
    with handle_api_error(
        operation="get_team_capacity_summary", context={"project_id": project_id}
    ):
        ref_date = reference_date or date.today()

        # Get all active capacity settings for the project
        query = select(CapacitySettings).where(
            and_(
                CapacitySettings.project_id == project_id,
                or_(CapacitySettings.valid_from.is_(None), CapacitySettings.valid_from <= ref_date),
                or_(CapacitySettings.valid_to.is_(None), CapacitySettings.valid_to >= ref_date),
            )
        )

        result = await db.execute(query)
        settings = result.scalars().all()

        if not settings:
            return TeamCapacitySummary(
                total_theoretical_hours=0,
                total_effective_hours=0,
                average_focus_factor=0.8,
                team_members=0,
                capacity_by_member=[],
            )

        total_theoretical = 0.0
        total_effective = 0.0
        total_focus_weighted = 0.0
        capacity_by_member = []

        for setting in settings:
            theoretical = setting.hours_per_week * sprint_weeks
            effective = setting.effective_capacity * sprint_weeks

            total_theoretical += theoretical
            total_effective += effective
            total_focus_weighted += setting.focus_factor * theoretical

            capacity_by_member.append(
                {
                    "assignee_email": setting.assignee_email,
                    "assignee_name": setting.assignee_name,
                    "hours_per_week": setting.hours_per_week,
                    "focus_factor": setting.focus_factor,
                    "theoretical_hours": round(theoretical, 2),
                    "effective_hours": round(effective, 2),
                    "notes": setting.notes,
                }
            )

        avg_focus = total_focus_weighted / total_theoretical if total_theoretical > 0 else 0.8

        return TeamCapacitySummary(
            total_theoretical_hours=round(total_theoretical, 2),
            total_effective_hours=round(total_effective, 2),
            average_focus_factor=round(avg_focus, 3),
            team_members=len(settings),
            capacity_by_member=capacity_by_member,
        )


@router.get("/summary", response_model=TeamCapacitySummary)
async def get_team_capacity_summary_legacy(
    project_id: int = Query(..., ge=1),
    sprint_weeks: float = Query(2.0, ge=0.5, le=8.0),
    reference_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Backward-compatible alias for older clients using query-based summary path.
    """
    return await get_team_capacity_summary(
        project_id=project_id,
        sprint_weeks=sprint_weeks,
        reference_date=reference_date,
        db=db,
    )


# =============================================================================
# Helper function for analytics endpoint integration
# =============================================================================


async def get_assignee_capacity(
    db: AsyncSession,
    assignee_email: str,
    project_id: Optional[int],
    reference_date: Optional[date] = None,
) -> tuple[float, float]:
    """
    Get capacity settings for an assignee.

    Returns (hours_per_week, focus_factor) tuple.
    Falls back to defaults (40.0, 0.8) if no setting found.
    """
    ref_date = reference_date or date.today()

    # Try project-specific first, then global
    query = (
        select(CapacitySettings)
        .where(
            and_(
                CapacitySettings.assignee_email == assignee_email,
                or_(CapacitySettings.valid_from.is_(None), CapacitySettings.valid_from <= ref_date),
                or_(CapacitySettings.valid_to.is_(None), CapacitySettings.valid_to >= ref_date),
            )
        )
        .order_by(
            # Prefer project-specific over global
            CapacitySettings.project_id.is_(None).asc()
        )
    )

    if project_id:
        query = query.where(
            or_(CapacitySettings.project_id == project_id, CapacitySettings.project_id.is_(None))
        )

    result = await db.execute(query)
    setting = result.scalars().first()

    if setting:
        return setting.hours_per_week, setting.focus_factor

    return 40.0, 0.8  # Defaults


# =============================================================================
# Team Health Check Endpoints
# =============================================================================


@router.get("/health-checks")
async def list_health_checks(
    project_id: int,
    sprint_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """List team health checks for a project with pagination metadata."""
    with handle_api_error(operation="list_health_checks", context={"project_id": project_id}):
        # Build base query with filters
        conditions = [TeamHealthCheck.project_id == project_id]
        if sprint_id:
            conditions.append(TeamHealthCheck.sprint_id == sprint_id)

        base_query = select(TeamHealthCheck).where(and_(*conditions))

        count_query = select(func.count()).select_from(base_query.subquery())
        data_query = (
            base_query.order_by(TeamHealthCheck.check_date.desc()).offset(skip).limit(limit)
        )

        # AsyncSession does not support concurrent operations on the same session.
        count_result = await db.execute(count_query)
        data_result = await db.execute(data_query)

        total = count_result.scalar() or 0
        checks = data_result.scalars().all()

        return paginated_response(
            data=[TeamHealthCheckSchema.model_validate(c).model_dump() for c in checks],
            total=total,
            skip=skip,
            limit=limit,
        )


@router.post("/health-checks", response_model=TeamHealthCheckSchema)
async def create_health_check(
    data: TeamHealthCheckCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new team health check.

    If happiness_index is not provided, it's calculated as a weighted average
    of the individual metrics.
    """
    async with async_handle_api_error(
        operation="create_health_check", context={"project_id": data.project_id}, db_session=db
    ):
        # Calculate happiness_index if not provided
        happiness = data.happiness_index
        if happiness is None:
            metrics = [
                data.satisfaction,
                data.workload_balance,
                data.collaboration_quality,
            ]
            # Technical debt pressure is inverted (high = bad)
            if data.technical_debt_pressure:
                metrics.append(6 - data.technical_debt_pressure)

            valid_metrics = [m for m in metrics if m is not None]
            if valid_metrics:
                happiness = sum(valid_metrics) / len(valid_metrics)

        check = TeamHealthCheck(
            project_id=data.project_id,
            sprint_id=data.sprint_id,
            satisfaction=data.satisfaction,
            workload_balance=data.workload_balance,
            technical_debt_pressure=data.technical_debt_pressure,
            collaboration_quality=data.collaboration_quality,
            happiness_index=happiness,
            burnout_risk_score=data.burnout_risk_score,
            burnout_risk_factors=data.burnout_risk_factors,
            check_date=data.check_date,
            respondent_count=data.respondent_count,
            notes=data.notes,
        )

        db.add(check)
        await db.commit()
        await db.refresh(check)

        return check


@router.get("/health-summary/{project_id}", response_model=TeamHealthSummary)
@cached_endpoint(
    key_builder=lambda project_id, **kw: CapacityCacheKeys.health_summary(project_id),
    tier=CacheTier.WARM,  # 5 min cache for health summary
)
async def get_health_summary(
    project_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get summary of team health metrics with trend analysis. Cached for 5 minutes."""
    with handle_api_error(operation="get_health_summary", context={"project_id": project_id}):
        query = (
            select(TeamHealthCheck)
            .where(TeamHealthCheck.project_id == project_id)
            .order_by(TeamHealthCheck.check_date.desc())
            .limit(limit)
        )

        result = await db.execute(query)
        checks = result.scalars().all()

        if not checks:
            return TeamHealthSummary(
                latest_happiness_index=None,
                latest_burnout_risk=None,
                trend_direction="stable",
                checks_count=0,
                trend_data=[],
            )

        # Latest values
        latest = checks[0]

        # Calculate trend
        trend_direction = "stable"
        if len(checks) >= 3:
            recent_avg = sum(c.happiness_index or 0 for c in checks[:3]) / 3
            older_avg = sum(c.happiness_index or 0 for c in checks[-3:]) / 3
            diff = recent_avg - older_avg
            if diff > 0.3:
                trend_direction = "improving"
            elif diff < -0.3:
                trend_direction = "declining"

        trend_data = [
            HealthTrend(
                check_date=c.check_date,
                happiness_index=c.happiness_index,
                burnout_risk_score=c.burnout_risk_score,
            )
            for c in reversed(checks)  # Chronological order
        ]

        return TeamHealthSummary(
            latest_happiness_index=latest.happiness_index,
            latest_burnout_risk=latest.burnout_risk_score,
            trend_direction=trend_direction,
            checks_count=len(checks),
            trend_data=trend_data,
        )


@router.get("/health-summary", response_model=TeamHealthSummary)
async def get_health_summary_legacy(
    project_id: int = Query(..., ge=1),
    period_days: Optional[int] = Query(None, ge=1, le=365),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Backward-compatible alias for older clients using query-based health summary path.
    """
    resolved_limit = limit
    if period_days is not None:
        # Older clients pass period_days; map it to bounded sample count.
        resolved_limit = max(1, min(50, period_days))
    return await get_health_summary(project_id=project_id, limit=resolved_limit, db=db)


# =============================================================================
# CFD Snapshot Endpoints
# =============================================================================


@router.get("/cfd/{project_id}", response_model=CFDData)
@cached_endpoint(
    key_builder=lambda project_id, **kw: CapacityCacheKeys.cfd_data(project_id),
    tier=CacheTier.WARM,  # 5 min cache for CFD data
)
async def get_cfd_data(
    project_id: int,
    sprint_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get CFD snapshot data for visualization. Cached for 5 minutes."""
    with handle_api_error(operation="get_cfd_data", context={"project_id": project_id}):
        query = select(CFDSnapshot).where(CFDSnapshot.project_id == project_id)

        if sprint_id:
            query = query.where(CFDSnapshot.sprint_id == sprint_id)
        if start_date:
            query = query.where(CFDSnapshot.snapshot_date >= start_date)
        if end_date:
            query = query.where(CFDSnapshot.snapshot_date <= end_date)

        query = query.order_by(CFDSnapshot.snapshot_date)

        result = await db.execute(query)
        snapshots = result.scalars().all()

        if not snapshots:
            return CFDData(
                snapshots=[],
                date_range={"start": date.today(), "end": date.today()},
                status_labels=["Backlog", "To Do", "In Progress", "In Review", "Testing", "Done"],
            )

        return CFDData(
            snapshots=[CFDSnapshotSchema.model_validate(s) for s in snapshots],
            date_range={
                "start": snapshots[0].snapshot_date,
                "end": snapshots[-1].snapshot_date,
            },
            status_labels=["Backlog", "To Do", "In Progress", "In Review", "Testing", "Done"],
        )


@router.get("/cfd", response_model=CFDData)
async def get_cfd_data_legacy(
    project_id: int = Query(..., ge=1),
    sprint_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Backward-compatible alias for older clients using query-based CFD path.
    """
    return await get_cfd_data(
        project_id=project_id,
        sprint_id=sprint_id,
        start_date=start_date,
        end_date=end_date,
        db=db,
    )


@router.post("/cfd/snapshot", response_model=CFDSnapshotSchema)
async def create_cfd_snapshot(
    project_id: int,
    sprint_id: Optional[int] = None,
    snapshot_date: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Create a CFD snapshot by counting current task statuses.

    This endpoint captures the current state of tasks for the project/sprint.
    Should be called daily (typically via scheduled job).
    """
    async with async_handle_api_error(
        operation="create_cfd_snapshot", context={"project_id": project_id}, db_session=db
    ):
        snap_date = snapshot_date or date.today()

        # Check if snapshot already exists for this date
        existing = await db.execute(
            select(CFDSnapshot).where(
                and_(
                    CFDSnapshot.project_id == project_id,
                    CFDSnapshot.snapshot_date == snap_date,
                    CFDSnapshot.sprint_id == sprint_id
                    if sprint_id
                    else CFDSnapshot.sprint_id.is_(None),
                )
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail=f"Snapshot already exists for {snap_date}")

        # Count tasks by status
        query = select(Task.status, func.count(Task.id).label("count")).where(
            Task.project_id == project_id
        )

        if sprint_id:
            query = query.where(Task.sprint_id == sprint_id)

        query = query.group_by(Task.status)

        result = await db.execute(query)
        status_counts = {row.status.lower(): row.count for row in result}

        # Map to CFD columns (status names vary by project)
        def get_count(*status_names):
            return sum(status_counts.get(s.lower(), 0) for s in status_names)

        snapshot = CFDSnapshot(
            project_id=project_id,
            sprint_id=sprint_id,
            snapshot_date=snap_date,
            backlog_count=get_count("backlog", "new", "open"),
            todo_count=get_count("to do", "todo", "selected for development"),
            in_progress_count=get_count("in progress", "in development", "active"),
            in_review_count=get_count("in review", "code review", "review"),
            testing_count=get_count("testing", "qa", "in testing", "test"),
            done_count=get_count("done", "closed", "resolved", "completed"),
        )

        # Calculate aggregates
        snapshot.total_count = (
            snapshot.backlog_count
            + snapshot.todo_count
            + snapshot.in_progress_count
            + snapshot.in_review_count
            + snapshot.testing_count
            + snapshot.done_count
        )
        snapshot.wip_count = (
            snapshot.in_progress_count + snapshot.in_review_count + snapshot.testing_count
        )
        snapshot.throughput = snapshot.done_count

        db.add(snapshot)
        await db.commit()
        await db.refresh(snapshot)

        logger.info(
            "Created CFD snapshot for project %d: total=%d, wip=%d, done=%d",
            project_id,
            snapshot.total_count,
            snapshot.wip_count,
            snapshot.done_count,
        )

        return snapshot


@router.get("/cfd/{project_id}/metrics", response_model=FlowMetrics)
@cached_endpoint(
    key_builder=lambda project_id, **kw: CapacityCacheKeys.flow_metrics(project_id),
    tier=CacheTier.WARM,  # 5 min cache for flow metrics
)
async def get_flow_metrics(
    project_id: int,
    sprint_id: Optional[int] = None,
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
):
    """Calculate flow metrics from CFD data. Cached for 5 minutes."""
    with handle_api_error(operation="get_flow_metrics", context={"project_id": project_id}):
        start_date = date.today()
        from datetime import timedelta

        start_date = start_date - timedelta(days=days)

        query = select(CFDSnapshot).where(
            and_(CFDSnapshot.project_id == project_id, CFDSnapshot.snapshot_date >= start_date)
        )

        if sprint_id:
            query = query.where(CFDSnapshot.sprint_id == sprint_id)

        query = query.order_by(CFDSnapshot.snapshot_date)

        result = await db.execute(query)
        snapshots = result.scalars().all()

        if len(snapshots) < 2:
            return FlowMetrics(
                avg_lead_time_days=None,
                avg_cycle_time_hours=None,
                avg_throughput_per_day=None,
                wip_trend="stable",
                bottleneck_status=None,
            )

        # Calculate throughput trend
        throughputs = [s.throughput or 0 for s in snapshots if s.throughput]
        avg_throughput = sum(throughputs) / len(throughputs) if throughputs else None

        # Calculate average cycle time
        cycle_times = [s.avg_cycle_time_hours for s in snapshots if s.avg_cycle_time_hours]
        avg_cycle = sum(cycle_times) / len(cycle_times) if cycle_times else None

        # WIP trend
        first_half = snapshots[: len(snapshots) // 2]
        second_half = snapshots[len(snapshots) // 2 :]

        first_wip = sum(s.wip_count or 0 for s in first_half) / len(first_half) if first_half else 0
        second_wip = (
            sum(s.wip_count or 0 for s in second_half) / len(second_half) if second_half else 0
        )

        wip_trend = "stable"
        if second_wip > first_wip * 1.2:
            wip_trend = "increasing"
        elif second_wip < first_wip * 0.8:
            wip_trend = "decreasing"

        # Find bottleneck (highest average WIP state)
        latest = snapshots[-1]
        status_wip = {
            "In Progress": latest.in_progress_count,
            "In Review": latest.in_review_count,
            "Testing": latest.testing_count,
        }
        bottleneck = (
            max(status_wip.items(), key=lambda item: item[1] or 0)[0]
            if any(status_wip.values())
            else None
        )

        return FlowMetrics(
            avg_lead_time_days=None,  # Would need task-level tracking
            avg_cycle_time_hours=round(avg_cycle, 2) if avg_cycle else None,
            avg_throughput_per_day=round(avg_throughput / 1, 2) if avg_throughput else None,
            wip_trend=wip_trend,
            bottleneck_status=bottleneck,
        )


@router.get("/flow-metrics", response_model=FlowMetrics)
async def get_flow_metrics_legacy(
    project_id: int = Query(..., ge=1),
    sprint_id: Optional[int] = None,
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
):
    """
    Backward-compatible alias for older clients using query-based flow metrics path.
    """
    return await get_flow_metrics(project_id=project_id, sprint_id=sprint_id, days=days, db=db)
