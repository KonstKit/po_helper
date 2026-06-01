"""Sprint Quality Report Generation endpoints."""

from datetime import timezone
from pathlib import Path

from .common import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Response,
    FileResponse,
    AsyncSession,
    Optional,
    datetime,
    timedelta,
    select,
    func,
    and_,
    Integer,
    get_db,
    # Models
    PullRequest,
    CoverageReport,
    QualityGateHistory,
    FlakyTest,
    ComponentCoverageModel,
    Project,
    Sprint,
    # Schemas
    ReportFormat,
    ReportSection,
    SprintQualityReport,
    ReportGenerationRequest,
    ReportGenerationResponse,
    TestCoverageSection,
    PRQualitySection,
    ComponentHealthItem,
    # Service
    report_service,
)
from .metrics import get_quality_summary

router = APIRouter()


def _resolve_report_download_path(filename: str) -> Path:
    reports_dir = Path(report_service.reports_dir).resolve()
    requested = Path(filename)

    if (
        requested.is_absolute()
        or requested.name != filename
        or filename in {".", ".."}
        or "\\" in filename
        or "/" in filename
    ):
        raise HTTPException(status_code=400, detail="Invalid report filename")

    resolved = (reports_dir / requested).resolve()
    if reports_dir not in resolved.parents or not resolved.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    return resolved


@router.get("/reports/data", response_model=SprintQualityReport)
async def get_report_data(
    project_id: int,
    sprint_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Get sprint quality report data (JSON format).
    This aggregates data from quality metrics, test coverage, and defects.
    """
    # Get project info
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one_or_none()
    project_name = project.name if project else None

    # Get sprint info
    sprint_name = None
    if sprint_id:
        sprint_result = await db.execute(select(Sprint).where(Sprint.id == sprint_id))
        sprint = sprint_result.scalar_one_or_none()
        sprint_name = sprint.name if sprint else None

    # Get quality summary
    quality_summary = await get_quality_summary(project_id, sprint_id, db)

    # Get test coverage data from latest coverage report
    coverage_result = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.project_id == project_id)
        .order_by(CoverageReport.created_at.desc())
        .limit(1)
    )
    latest_coverage = coverage_result.scalar_one_or_none()

    # Get flaky test count
    flaky_result = await db.execute(
        select(func.count(FlakyTest.id)).where(
            and_(
                FlakyTest.project_id == project_id,
                FlakyTest.status == "active",
            )
        )
    )
    flaky_count = flaky_result.scalar() or 0

    test_coverage = None
    if latest_coverage:
        total_tests = latest_coverage.total_tests or 0
        passed_tests = latest_coverage.passed_tests or 0
        test_coverage = TestCoverageSection(
            line_coverage=latest_coverage.line_coverage,
            branch_coverage=latest_coverage.branch_coverage,
            function_coverage=latest_coverage.function_coverage,
            coverage_target=0.8,
            coverage_met=(latest_coverage.line_coverage or 0) >= 0.8,
            total_tests=total_tests,
            passed_tests=passed_tests,
            failed_tests=latest_coverage.failed_tests or 0,
            skipped_tests=latest_coverage.skipped_tests or 0,
            test_pass_rate=(passed_tests / total_tests) if total_tests else 0.0,
            flaky_test_count=flaky_count,
        )

    # Get PR quality data
    pr_result = await db.execute(
        select(
            func.count(PullRequest.id).label("total"),
            func.sum(func.cast(PullRequest.merged, Integer)).label("merged"),
        ).where(
            and_(
                PullRequest.project_id == project_id,
                PullRequest.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
    )
    pr_data = pr_result.first()

    # Get quality gate history for pass rate
    gate_result = await db.execute(
        select(
            func.count(QualityGateHistory.id).label("total"),
            func.sum(func.cast(QualityGateHistory.passed, Integer)).label("passed"),
        ).where(
            and_(
                QualityGateHistory.project_id == project_id,
                QualityGateHistory.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
            )
        )
    )
    gate_data = gate_result.first()

    pr_quality = PRQualitySection(
        total_prs_merged=pr_data.merged or 0 if pr_data else 0,
        prs_meeting_gates=gate_data.passed or 0 if gate_data else 0,
        gate_pass_rate=(gate_data.passed / gate_data.total)
        if gate_data and gate_data.total
        else 0.0,
    )

    # Get component health data
    component_result = await db.execute(
        select(ComponentCoverageModel)
        .where(ComponentCoverageModel.project_id == project_id)
        .order_by(ComponentCoverageModel.risk_score.desc().nullsfirst())
        .limit(20)
    )
    components = component_result.scalars().all()

    component_health = [
        ComponentHealthItem(
            component=c.component_path,
            coverage=c.line_coverage,
            defect_count=0,  # Would need to correlate with defects
            flaky_test_count=0,  # Would need to correlate with flaky tests
            risk_score=c.risk_score or 0.0,
            priority=c.priority or "medium",
        )
        for c in components
    ]

    # Generate report data
    report = report_service.generate_report_data(
        project_id=project_id,
        project_name=project_name,
        sprint_id=sprint_id,
        sprint_name=sprint_name,
        quality_summary=quality_summary,
        test_coverage=test_coverage,
        pr_quality=pr_quality,
        component_health=component_health,
    )

    return report


@router.post("/reports/generate", response_model=ReportGenerationResponse)
async def generate_report(
    request: ReportGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a quality report in the specified format (PDF, Excel, JSON).
    Returns download URL for the generated report.
    """
    try:
        # Get report data
        report_data = await get_report_data(request.project_id, request.sprint_id, db)

        # Generate and save report
        filename, filepath, size_bytes = report_service.save_report(
            report=report_data,
            format=request.format,
            sections=request.sections,
        )

        return ReportGenerationResponse(
            success=True,
            report_id=report_data.report_id,
            download_url=f"/api/v1/quality/reports/download/{filename}",
            file_name=filename,
            format=request.format,
            generated_at=datetime.now(timezone.utc),
            file_size_bytes=size_bytes,
        )
    except Exception as e:
        return ReportGenerationResponse(
            success=False,
            format=request.format,
            generated_at=datetime.now(timezone.utc),
            error=str(e),
        )


@router.get("/reports/download/{filename}")
async def download_report(filename: str):
    """Download a generated report file."""
    filepath = _resolve_report_download_path(filename)

    # Determine media type
    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif filename.endswith(".json"):
        media_type = "application/json"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type=media_type,
    )


@router.get("/reports/preview")
async def preview_report(
    project_id: int,
    sprint_id: Optional[int] = None,
    format: ReportFormat = Query(ReportFormat.pdf),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate and return report content directly (for preview).
    Useful for in-browser PDF viewing or JSON inspection.
    """
    # Get report data
    report_data = await get_report_data(project_id, sprint_id, db)

    # Generate content based on format
    if format == ReportFormat.pdf:
        content = report_service.generate_pdf(
            report_data,
            [
                ReportSection.executive_summary,
                ReportSection.quality_metrics,
                ReportSection.test_coverage,
                ReportSection.recommendations,
            ],
        )
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="quality_report.pdf"'},
        )
    elif format == ReportFormat.excel:
        content = report_service.generate_excel(
            report_data,
            [
                ReportSection.executive_summary,
                ReportSection.component_health,
                ReportSection.recommendations,
            ],
        )
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="quality_report.xlsx"'},
        )
    else:
        return report_data
