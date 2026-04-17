"""Quality Metrics, Summary, Trends, and Dashboard endpoints."""

from datetime import timezone

from .common import (
    APIRouter,
    Depends,
    Query,
    AsyncSession,
    Optional,
    List,
    datetime,
    timedelta,
    select,
    func,
    and_,
    Integer,
    case,
    get_db,
    transactional_session,
    # Models
    EscapedDefect,
    DefectMetrics,
    # Schemas
    DefectMetricsSchema,
    QualitySummary,
    QualityTrendData,
    DefectTrend,
    RootCauseAnalysis,
    ComponentAnalysis,
    QualityDashboard,
    # Cache
    cached_endpoint,
    CacheTier,
    QualityCacheKeys,
)

router = APIRouter()


@router.get("/summary", response_model=QualitySummary)
@cached_endpoint(
    key_builder=lambda project_id, sprint_id=None, **kw: QualityCacheKeys.summary(
        project_id, sprint_id
    ),
    tier=CacheTier.HOT,  # 60 sec cache for frequently accessed data
)
async def get_quality_summary(
    project_id: int,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get quality summary metrics for a project or sprint. Cached for 60s."""
    base_filter = [EscapedDefect.project_id == project_id]
    if sprint_id:
        base_filter.append(EscapedDefect.sprint_id == sprint_id)

    # Total and status counts
    result = await db.execute(
        select(
            func.count(EscapedDefect.id).label("total"),
            func.sum(func.cast(EscapedDefect.status == "open", Integer)).label("open"),
            func.sum(func.cast(EscapedDefect.status.in_(["resolved", "closed"]), Integer)).label(
                "resolved"
            ),
        ).where(and_(*base_filter))
    )
    counts = result.first()

    # Severity breakdown
    severity_result = await db.execute(
        select(
            EscapedDefect.severity,
            func.count(EscapedDefect.id).label("count"),
        )
        .where(and_(*base_filter))
        .group_by(EscapedDefect.severity)
    )
    severity_counts = {row.severity: row.count for row in severity_result}

    # MTTR calculation (only resolved defects)
    mttr_result = await db.execute(
        select(func.avg(EscapedDefect.time_to_resolve_hours)).where(
            and_(*base_filter, EscapedDefect.time_to_resolve_hours.isnot(None))
        )
    )
    mttr = mttr_result.scalar()

    # MTTD calculation
    mttd_result = await db.execute(
        select(func.avg(EscapedDefect.time_to_detect_hours)).where(
            and_(*base_filter, EscapedDefect.time_to_detect_hours.isnot(None))
        )
    )
    mttd = mttd_result.scalar()

    # Get latest metrics if available
    metrics_result = await db.execute(
        select(DefectMetrics)
        .where(DefectMetrics.project_id == project_id)
        .order_by(DefectMetrics.period_end.desc())
        .limit(1)
    )
    latest_metrics = metrics_result.scalars().first()

    # Calculate trend
    trend_direction = "stable"
    trend_change = None
    if latest_metrics:
        # Compare with previous period
        prev_result = await db.execute(
            select(DefectMetrics)
            .where(
                and_(
                    DefectMetrics.project_id == project_id,
                    DefectMetrics.period_end < latest_metrics.period_start,
                )
            )
            .order_by(DefectMetrics.period_end.desc())
            .limit(1)
        )
        prev_metrics = prev_result.scalars().first()
        if (
            prev_metrics
            and latest_metrics.defect_removal_efficiency
            and prev_metrics.defect_removal_efficiency
        ):
            change = (
                latest_metrics.defect_removal_efficiency - prev_metrics.defect_removal_efficiency
            )
            trend_change = change
            if change > 2:
                trend_direction = "improving"
            elif change < -2:
                trend_direction = "declining"

    return QualitySummary(
        project_id=project_id,
        sprint_id=sprint_id,
        total_escaped_defects=counts.total or 0,
        open_defects=counts.open or 0,
        resolved_defects=counts.resolved or 0,
        critical_count=severity_counts.get("critical", 0),
        high_count=severity_counts.get("high", 0),
        medium_count=severity_counts.get("medium", 0),
        low_count=severity_counts.get("low", 0),
        defect_density=latest_metrics.defect_density if latest_metrics else None,
        defect_removal_efficiency=latest_metrics.defect_removal_efficiency
        if latest_metrics
        else None,
        escape_rate=latest_metrics.escape_rate if latest_metrics else None,
        mttr_hours=float(mttr) if mttr else None,
        mttd_hours=float(mttd) if mttd else None,
        trend_direction=trend_direction,
        trend_change_percent=trend_change,
    )


@router.get("/root-cause-analysis", response_model=List[RootCauseAnalysis])
@cached_endpoint(
    key_builder=lambda project_id, sprint_id=None, **kw: QualityCacheKeys.root_cause_analysis(
        project_id, sprint_id
    ),
    tier=CacheTier.WARM,  # 5 min cache
)
async def get_root_cause_analysis(
    project_id: int,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get root cause breakdown for defects. Cached for 5 min."""
    base_filter = [EscapedDefect.project_id == project_id]
    if sprint_id:
        base_filter.append(EscapedDefect.sprint_id == sprint_id)

    # Total count for percentage
    total_result = await db.execute(select(func.count(EscapedDefect.id)).where(and_(*base_filter)))
    total = total_result.scalar() or 0

    if total == 0:
        return []

    # Group by root cause
    result = await db.execute(
        select(
            EscapedDefect.root_cause,
            func.count(EscapedDefect.id).label("count"),
            func.avg(EscapedDefect.time_to_resolve_hours).label("avg_ttr"),
        )
        .where(and_(*base_filter))
        .group_by(EscapedDefect.root_cause)
    )

    items: List[RootCauseAnalysis] = []
    for row in result:
        count_val = int(getattr(row, "count", 0) or 0)
        avg_ttr_val = getattr(row, "avg_ttr", None)
        items.append(
            RootCauseAnalysis(
                root_cause=row.root_cause or "unknown",
                count=count_val,
                percentage=round((count_val / total) * 100, 1),
                avg_time_to_resolve_hours=float(avg_ttr_val) if avg_ttr_val else None,
            )
        )

    return items


@router.get("/component-analysis", response_model=List[ComponentAnalysis])
@cached_endpoint(
    key_builder=lambda project_id, sprint_id=None, **kw: QualityCacheKeys.component_analysis(
        project_id, sprint_id
    ),
    tier=CacheTier.WARM,  # 5 min cache - data changes less frequently
)
async def get_component_analysis(
    project_id: int,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get defect analysis by affected component. Cached for 5 min.

    Optimized: single query with SQL CASE aggregation instead of N+1.
    """
    base_filter = [
        EscapedDefect.project_id == project_id,
        EscapedDefect.affected_component.isnot(None),
    ]
    if sprint_id:
        base_filter.append(EscapedDefect.sprint_id == sprint_id)

    # Calculate avg_severity directly in SQL using CASE statement
    # Mapping: critical=4, high=3, medium=2, low=1, default=2
    severity_case = case(
        (EscapedDefect.severity == "critical", 4),
        (EscapedDefect.severity == "high", 3),
        (EscapedDefect.severity == "medium", 2),
        (EscapedDefect.severity == "low", 1),
        else_=2,
    )

    result = await db.execute(
        select(
            EscapedDefect.affected_component,
            func.count(EscapedDefect.id).label("defect_count"),
            func.sum(func.cast(EscapedDefect.severity == "critical", Integer)).label(
                "critical_count"
            ),
            func.avg(severity_case).label("avg_severity"),
        )
        .where(and_(*base_filter))
        .group_by(EscapedDefect.affected_component)
        .order_by(func.count(EscapedDefect.id).desc())
    )

    return [
        ComponentAnalysis(
            component=row.affected_component,
            defect_count=row.defect_count,
            critical_count=row.critical_count or 0,
            avg_severity_score=round(float(row.avg_severity or 2), 2),
        )
        for row in result
    ]


@router.get("/trend", response_model=QualityTrendData)
@cached_endpoint(
    key_builder=lambda project_id, days=30, **kw: QualityCacheKeys.trend(project_id, days),
    tier=CacheTier.WARM,  # 5 min cache for trend data
)
async def get_quality_trend(
    project_id: int,
    days: int = Query(30, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get quality trend data over time. Cached for 5 min."""
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # Get daily defect counts
    result = await db.execute(
        select(
            func.date(EscapedDefect.detected_at).label("date"),
            func.count(EscapedDefect.id).label("escaped"),
        )
        .where(
            and_(
                EscapedDefect.project_id == project_id,
                EscapedDefect.detected_at >= start_date,
            )
        )
        .group_by(func.date(EscapedDefect.detected_at))
        .order_by(func.date(EscapedDefect.detected_at))
    )

    # Get resolved counts per day
    resolved_result = await db.execute(
        select(
            func.date(EscapedDefect.resolved_at).label("date"),
            func.count(EscapedDefect.id).label("resolved"),
        )
        .where(
            and_(
                EscapedDefect.project_id == project_id,
                EscapedDefect.resolved_at >= start_date,
                EscapedDefect.resolved_at.isnot(None),
            )
        )
        .group_by(func.date(EscapedDefect.resolved_at))
    )
    resolved_by_date = {row.date: row.resolved for row in resolved_result}

    # Get metrics data for DRE
    metrics_result = await db.execute(
        select(DefectMetrics)
        .where(
            and_(
                DefectMetrics.project_id == project_id,
                DefectMetrics.period_start >= start_date,
            )
        )
        .order_by(DefectMetrics.period_start)
    )
    metrics_by_date = {m.period_start.date(): m for m in metrics_result.scalars()}

    trends = []
    running_total = 0
    for row in result:
        date_key = row.date
        running_total += row.escaped
        resolved = resolved_by_date.get(date_key, 0)
        metrics = metrics_by_date.get(date_key)

        trends.append(
            DefectTrend(
                date=datetime.combine(date_key, datetime.min.time(), tzinfo=timezone.utc),
                total_defects=running_total,
                escaped_defects=row.escaped,
                resolved_defects=resolved,
                dre=metrics.defect_removal_efficiency if metrics else None,
            )
        )

    return QualityTrendData(
        project_id=project_id,
        trends=trends,
        period_days=days,
    )


@router.get("/dashboard", response_model=QualityDashboard)
@cached_endpoint(
    key_builder=lambda project_id, sprint_id=None, **kw: QualityCacheKeys.dashboard(
        project_id, sprint_id
    ),
    tier=CacheTier.HOT,  # 60 sec cache for dashboard composite
)
async def get_quality_dashboard(
    project_id: int,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get complete quality dashboard data. Cached for 60s."""
    summary = await get_quality_summary(project_id, sprint_id, db)
    root_causes = await get_root_cause_analysis(project_id, sprint_id, db)
    components = await get_component_analysis(project_id, sprint_id, db)
    trends = await get_quality_trend(project_id, 30, db)

    # Get recent defects
    defects_result = await db.execute(
        select(EscapedDefect)
        .where(EscapedDefect.project_id == project_id)
        .order_by(EscapedDefect.detected_at.desc())
        .limit(10)
    )
    recent_defects = defects_result.scalars().all()

    return QualityDashboard(
        summary=summary,
        recent_defects=recent_defects,
        root_cause_breakdown=root_causes,
        component_analysis=components,
        trend_data=trends,
    )


# =====================================================
# Defect Metrics Calculation
# =====================================================


@router.post("/metrics/calculate")
async def calculate_defect_metrics(
    project_id: int,
    sprint_id: Optional[int] = None,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    lines_of_code: Optional[int] = None,
    defects_found_in_dev: int = 0,
    defects_found_in_qa: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate and store defect metrics for a period.

    DRE (Defect Removal Efficiency) = (defects_before_release / total_defects) * 100
    Defect Density = defects / KLOC
    Escape Rate = escaped_defects / total_defects * 100
    """
    if not period_start:
        period_start = datetime.now(timezone.utc) - timedelta(days=14)
    if not period_end:
        period_end = datetime.now(timezone.utc)

    base_filter = [
        EscapedDefect.project_id == project_id,
        EscapedDefect.detected_at >= period_start,
        EscapedDefect.detected_at <= period_end,
    ]
    if sprint_id:
        base_filter.append(EscapedDefect.sprint_id == sprint_id)

    # Count escaped defects
    escaped_result = await db.execute(
        select(func.count(EscapedDefect.id)).where(and_(*base_filter))
    )
    defects_found_in_prod = escaped_result.scalar() or 0

    # Severity breakdown
    severity_result = await db.execute(
        select(
            EscapedDefect.severity,
            func.count(EscapedDefect.id).label("count"),
        )
        .where(and_(*base_filter))
        .group_by(EscapedDefect.severity)
    )
    severity_counts = {row.severity: row.count for row in severity_result}

    # MTTR and MTTD
    mttr_result = await db.execute(
        select(func.avg(EscapedDefect.time_to_resolve_hours)).where(
            and_(*base_filter, EscapedDefect.time_to_resolve_hours.isnot(None))
        )
    )
    mttr = mttr_result.scalar()

    mttd_result = await db.execute(
        select(func.avg(EscapedDefect.time_to_detect_hours)).where(
            and_(*base_filter, EscapedDefect.time_to_detect_hours.isnot(None))
        )
    )
    mttd = mttd_result.scalar()

    # Calculate metrics
    total_defects = defects_found_in_dev + defects_found_in_qa + defects_found_in_prod
    defects_before_release = defects_found_in_dev + defects_found_in_qa

    dre = (defects_before_release / total_defects * 100) if total_defects > 0 else None
    escape_rate = (defects_found_in_prod / total_defects * 100) if total_defects > 0 else None
    defect_density = (
        (total_defects / (lines_of_code / 1000)) if lines_of_code and lines_of_code > 0 else None
    )

    # Create metrics record
    metrics = DefectMetrics(
        project_id=project_id,
        sprint_id=sprint_id,
        period_start=period_start,
        period_end=period_end,
        total_defects=total_defects,
        defects_found_in_dev=defects_found_in_dev,
        defects_found_in_qa=defects_found_in_qa,
        defects_found_in_prod=defects_found_in_prod,
        critical_defects=severity_counts.get("critical", 0),
        high_defects=severity_counts.get("high", 0),
        medium_defects=severity_counts.get("medium", 0),
        low_defects=severity_counts.get("low", 0),
        defect_density=defect_density,
        defect_removal_efficiency=dre,
        escape_rate=escape_rate,
        mean_time_to_resolve_hours=float(mttr) if mttr else None,
        mean_time_to_detect_hours=float(mttd) if mttd else None,
        lines_of_code=lines_of_code,
    )

    async with transactional_session(db):
        db.add(metrics)
    await db.refresh(metrics)

    return {
        "id": metrics.id,
        "project_id": project_id,
        "sprint_id": sprint_id,
        "period": f"{period_start.date()} to {period_end.date()}",
        "total_defects": total_defects,
        "defect_removal_efficiency": round(dre, 2) if dre else None,
        "escape_rate": round(escape_rate, 2) if escape_rate else None,
        "defect_density": round(defect_density, 3) if defect_density else None,
        "mttr_hours": round(float(mttr), 2) if mttr else None,
        "mttd_hours": round(float(mttd), 2) if mttd else None,
    }


@router.get("/metrics", response_model=List[DefectMetricsSchema])
async def list_defect_metrics(
    project_id: int,
    sprint_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List defect metrics history with pagination."""
    q = select(DefectMetrics).where(DefectMetrics.project_id == project_id)
    if sprint_id:
        q = q.where(DefectMetrics.sprint_id == sprint_id)
    q = q.order_by(DefectMetrics.period_end.desc()).offset(skip).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()
