from __future__ import annotations

from typing import Optional, Dict, Any, List, Set, Sequence
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc, Integer
from app.core.database import get_db
from app.models import TestResult, CoverageReport, Artifact, ArtifactLink
from app.models.testing import FileCoverage, FlakyTest, CoverageHistory, ComponentCoverage
from app.schemas.testing import (
    FlakyTest as FlakyTestSchema,
    FlakyTestCreate,
    FlakyTestUpdate,
    FlakyTestSummary,
    CoverageHistoryCreate,
    ComponentCoverage as ComponentCoverageSchema,
    ComponentCoverageCreate,
    ComponentCoverageSummary,
    DeltaCoverage,
    FileCoverageDelta,
    CoverageTrend,
    CoverageTrendPoint,
    TestAnalyticsDashboard,
)
from app.utils.pagination import paginate_query, count_with_filters
from app.schemas.pagination import paginated_response, PaginationMeta

router = APIRouter()


async def _get_allowed_commit_shas_for_project(
    project_id: Optional[int],
    db: AsyncSession,
) -> Optional[Set[str]]:
    """
    Get all commit SHAs linked to a project via artifact links.

    This is the efficient version that queries from the artifact graph
    without requiring data to be loaded first.

    Args:
        project_id: Project ID to filter by, or None to skip filtering
        db: Database session

    Returns:
        Set of allowed commit SHAs if project_id is provided, None otherwise
    """
    if project_id is None:
        return None

    # Get all issue artifacts for this project
    res_issues = await db.execute(
        select(Artifact.id).where(Artifact.type == "jira_issue", Artifact.project_id == project_id)
    )
    issue_ids = {row[0] for row in res_issues.fetchall()}

    if not issue_ids:
        return set()

    # Get links pointing to these issues (from commits)
    res_links = await db.execute(
        select(ArtifactLink.from_artifact_id).where(ArtifactLink.to_artifact_id.in_(issue_ids))
    )
    commit_artifact_ids = {row[0] for row in res_links.fetchall()}

    if not commit_artifact_ids:
        return set()

    # Get commit SHAs from artifact external_ids
    res_commits = await db.execute(
        select(Artifact.external_id).where(
            Artifact.id.in_(commit_artifact_ids), Artifact.type == "commit"
        )
    )
    allowed_shas = {row[0] for row in res_commits.fetchall() if row[0]}

    return allowed_shas


async def _filter_commits_by_project(
    items: Sequence[Any],
    project_id: Optional[int],
    db: AsyncSession,
) -> Optional[Set[str]]:
    """
    Filter commit SHAs by project through commit->issue artifact links.

    DEPRECATED: Use _get_allowed_commit_shas_for_project() for better performance.
    This function is kept for backward compatibility with detection/analysis endpoints.

    Args:
        items: List of objects with commit_sha attribute (TestResult, CoverageReport, etc.)
        project_id: Project ID to filter by, or None to skip filtering
        db: Database session

    Returns:
        Set of allowed commit SHAs if project_id is provided, None otherwise
    """
    if project_id is None:
        return None

    shas = sorted({i.commit_sha for i in items if i.commit_sha})
    if not shas:
        return set()

    # Get commit artifacts
    res_commit = await db.execute(
        select(Artifact).where(Artifact.type == "commit", Artifact.external_id.in_(shas))
    )
    commits = {a.id: a.external_id for a in res_commit.scalars().all()}

    # Get links from commits to issues
    res_links = await db.execute(
        select(ArtifactLink).where(ArtifactLink.from_artifact_id.in_(list(commits.keys())))
    )
    links = res_links.scalars().all()
    to_ids = [link.to_artifact_id for link in links]

    if not to_ids:
        return set()

    # Get issues for this project
    res_issues = await db.execute(
        select(Artifact).where(
            Artifact.id.in_(to_ids),
            Artifact.type == "jira_issue",
            Artifact.project_id == project_id,
        )
    )
    issues = res_issues.scalars().all()
    ok_issue_ids = {i.id for i in issues}
    ok_commit_ids = {link.from_artifact_id for link in links if link.to_artifact_id in ok_issue_ids}
    allowed_shas = {commits[cid] for cid in ok_commit_ids if cid in commits}

    return allowed_shas


@router.get("/runs")
async def list_test_runs(
    project_id: Optional[int] = None,
    provider: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List test runs grouped by (provider, commit_sha, pr_number).

    Uses database-level aggregation instead of loading all records into memory.
    """
    # Get allowed commit SHAs for project filtering
    allowed_shas = await _get_allowed_commit_shas_for_project(project_id, db)

    # Build base query with GROUP BY at database level
    base_query = select(
        TestResult.provider,
        TestResult.commit_sha,
        TestResult.pr_number,
        func.max(TestResult.created_at).label("created_at"),
        func.count(TestResult.id).label("total"),
        func.sum(func.cast(func.lower(TestResult.status) == "failed", Integer)).label("failed"),
        func.sum(func.cast(func.lower(TestResult.status) == "error", Integer)).label("error"),
        func.sum(func.cast(func.lower(TestResult.status) == "skipped", Integer)).label("skipped"),
    ).group_by(
        TestResult.provider,
        TestResult.commit_sha,
        TestResult.pr_number,
    )

    # Apply filters
    filters = []
    if provider:
        filters.append(func.lower(TestResult.provider) == provider.lower())
    if allowed_shas is not None:
        if not allowed_shas:
            # No commits linked to this project
            return {"data": [], "meta": PaginationMeta.from_offset(0, skip, limit).model_dump()}
        filters.append(TestResult.commit_sha.in_(allowed_shas))

    if filters:
        base_query = base_query.where(and_(*filters))

    # Get total count (subquery for grouped results)
    count_subquery = base_query.subquery()
    count_result = await db.execute(select(func.count()).select_from(count_subquery))
    total = count_result.scalar() or 0

    # Apply sorting and pagination
    paginated_query = base_query.order_by(desc("created_at")).offset(skip).limit(limit)

    result = await db.execute(paginated_query)
    rows = result.mappings().all()

    runs = [
        {
            "provider": row["provider"],
            "commit_sha": row["commit_sha"],
            "pr_number": row["pr_number"],
            "created_at": row["created_at"],
            "total": row["total"] or 0,
            "failed": row["failed"] or 0,
            "error": row["error"] or 0,
            "skipped": row["skipped"] or 0,
        }
        for row in rows
    ]

    return paginated_response(runs, total, skip, limit)


@router.get("/results")
async def list_test_results(
    project_id: Optional[int] = None,
    commit_sha: Optional[str] = None,
    status: Optional[str] = None,
    since_days: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """
    List test results with proper database-level pagination.

    Filters are applied at the database level for efficiency.
    """
    # Get allowed commit SHAs for project filtering
    allowed_shas = await _get_allowed_commit_shas_for_project(project_id, db)

    # Build filters list
    filters = []

    if commit_sha:
        filters.append(TestResult.commit_sha == commit_sha)

    if status:
        filters.append(func.lower(TestResult.status) == status.lower())

    if since_days is not None and since_days > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        filters.append(TestResult.created_at >= cutoff)

    if allowed_shas is not None:
        if not allowed_shas:
            # No commits linked to this project
            return paginated_response([], 0, skip, limit)
        filters.append(TestResult.commit_sha.in_(allowed_shas))

    # Build query
    query = select(TestResult)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(TestResult.created_at))

    # Get total count
    total = await count_with_filters(db, TestResult, filters if filters else None)

    # Get paginated results
    items = await paginate_query(db, query, skip, limit)

    # Format results
    results = [
        {
            "id": it.id,
            "provider": it.provider,
            "commit_sha": it.commit_sha,
            "pr_number": it.pr_number,
            "suite": it.suite,
            "classname": it.classname,
            "name": it.name,
            "status": it.status,
            "duration": it.duration,
            "message": it.message,
            "created_at": it.created_at,
            "raw": it.raw,
        }
        for it in items
    ]

    return paginated_response(results, total, skip, limit)


@router.get("/coverage/list")
async def list_coverage(
    project_id: Optional[int] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    List coverage reports with proper database-level pagination.
    """
    # Get allowed commit SHAs for project filtering
    allowed_shas = await _get_allowed_commit_shas_for_project(project_id, db)

    # Build filters
    filters = []
    if allowed_shas is not None:
        if not allowed_shas:
            # No commits linked to this project
            return paginated_response([], 0, skip, limit)
        filters.append(CoverageReport.commit_sha.in_(allowed_shas))

    # Build query
    query = select(CoverageReport)
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(desc(CoverageReport.created_at))

    # Get total count
    total = await count_with_filters(db, CoverageReport, filters if filters else None)

    # Get paginated results
    items = await paginate_query(db, query, skip, limit)

    # Format results
    coverage = [
        {
            "id": it.id,
            "provider": it.provider,
            "commit_sha": it.commit_sha,
            "pr_number": it.pr_number,
            "line_coverage": it.line_coverage,
            "branch_coverage": it.branch_coverage,
            "report_url": it.report_url,
            "created_at": it.created_at,
        }
        for it in items
    ]

    return paginated_response(coverage, total, skip, limit)


@router.get("/coverage/{commit_sha}/files")
async def list_coverage_files(
    commit_sha: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """
    List file-level coverage for a specific commit.

    Paginated endpoint - use skip/limit for large codebases.
    """
    # Get latest coverage report for this commit
    res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.commit_sha == commit_sha)
        .order_by(CoverageReport.created_at.desc())
    )
    cov = res.scalars().first()
    if not cov:
        return paginated_response([], 0, skip, limit)

    # Count total files for this coverage report
    count_res = await db.execute(
        select(func.count(FileCoverage.id)).where(FileCoverage.coverage_report_id == cov.id)
    )
    total = count_res.scalar() or 0

    # Get paginated file coverage data
    files_res = await db.execute(
        select(FileCoverage)
        .where(FileCoverage.coverage_report_id == cov.id)
        .order_by(FileCoverage.file_path)
        .offset(skip)
        .limit(limit)
    )
    rows = files_res.scalars().all()

    files = [
        {
            "file_path": r.file_path,
            "line_coverage": r.line_coverage,
            "branch_coverage": r.branch_coverage,
            "lines_covered": r.lines_covered,
            "lines_total": r.lines_total,
        }
        for r in rows
    ]

    return paginated_response(files, total, skip, limit)


# =============================================================================
# FLAKY TESTS ENDPOINTS
# =============================================================================


@router.post("/flaky-tests", response_model=FlakyTestSchema)
async def create_flaky_test(
    data: FlakyTestCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create or update a flaky test record."""
    # Check if already exists
    res = await db.execute(
        select(FlakyTest).where(
            FlakyTest.project_id == data.project_id,
            FlakyTest.test_name == data.test_name,
            FlakyTest.classname == data.classname,
            FlakyTest.suite == data.suite,
        )
    )
    existing = res.scalars().first()

    if existing:
        # Update existing
        existing.total_runs = data.total_runs
        existing.failure_count = data.failure_count
        existing.flakiness_rate = data.failure_count / data.total_runs if data.total_runs > 0 else 0
        existing.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(existing)
        return existing

    flaky = FlakyTest(
        project_id=data.project_id,
        suite=data.suite,
        classname=data.classname,
        test_name=data.test_name,
        total_runs=data.total_runs,
        failure_count=data.failure_count,
        flakiness_rate=(data.failure_count / data.total_runs if data.total_runs > 0 else 0),
        status=data.status.value if data.status else "active",
        suspected_cause=data.suspected_cause.value if data.suspected_cause else None,
        failure_patterns=data.failure_patterns,
        affected_commits=data.affected_commits,
    )
    db.add(flaky)
    await db.commit()
    await db.refresh(flaky)
    return flaky


@router.get("/flaky-tests", response_model=List[FlakyTestSchema])
async def list_flaky_tests(
    project_id: int,
    status: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List flaky tests for a project with pagination."""
    q = select(FlakyTest).where(FlakyTest.project_id == project_id)
    if status:
        q = q.where(FlakyTest.status == status)
    q = q.order_by(FlakyTest.flakiness_rate.desc()).offset(skip).limit(limit)

    res = await db.execute(q)
    return res.scalars().all()


@router.get("/flaky-tests/{flaky_id}", response_model=FlakyTestSchema)
async def get_flaky_test(
    flaky_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific flaky test."""
    res = await db.execute(select(FlakyTest).where(FlakyTest.id == flaky_id))
    flaky = res.scalars().first()
    if not flaky:
        raise HTTPException(status_code=404, detail="Flaky test not found")
    return flaky


@router.patch("/flaky-tests/{flaky_id}", response_model=FlakyTestSchema)
async def update_flaky_test(
    flaky_id: int,
    data: FlakyTestUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a flaky test status or assignment."""
    res = await db.execute(select(FlakyTest).where(FlakyTest.id == flaky_id))
    flaky = res.scalars().first()
    if not flaky:
        raise HTTPException(status_code=404, detail="Flaky test not found")

    if data.status is not None:
        flaky.status = data.status.value
    if data.suspected_cause is not None:
        flaky.suspected_cause = data.suspected_cause.value
    if data.assigned_to is not None:
        flaky.assigned_to = data.assigned_to
    if data.fix_pr_number is not None:
        flaky.fix_pr_number = data.fix_pr_number
    if data.notes is not None:
        flaky.notes = data.notes

    flaky.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(flaky)
    return flaky


@router.delete("/flaky-tests/{flaky_id}")
async def delete_flaky_test(
    flaky_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a flaky test record."""
    res = await db.execute(select(FlakyTest).where(FlakyTest.id == flaky_id))
    flaky = res.scalars().first()
    if not flaky:
        raise HTTPException(status_code=404, detail="Flaky test not found")

    await db.delete(flaky)
    await db.commit()
    return {"status": "deleted", "id": flaky_id}


@router.post("/flaky-tests/detect")
async def detect_flaky_tests(
    project_id: int,
    days: int = 30,
    min_runs: int = 5,
    flakiness_threshold: float = 0.1,
    db: AsyncSession = Depends(get_db),
):
    """
    Analyze test history to detect flaky tests.

    A test is considered flaky if it has both passes and failures
    for the same commit, or if its pass rate is between threshold and 1.0.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get all test results in the period
    res = await db.execute(select(TestResult).where(TestResult.created_at >= cutoff))
    results = res.scalars().all()

    # Filter by project if needed
    allowed_shas = await _filter_commits_by_project(results, project_id, db)
    if allowed_shas is not None:
        results = [r for r in results if r.commit_sha in allowed_shas]

    # Group by test identifier
    test_stats: Dict[tuple, Dict[str, Any]] = {}
    for r in results:
        key = (r.suite or "", r.classname or "", r.name or "")
        if key not in test_stats:
            test_stats[key] = {
                "suite": r.suite,
                "classname": r.classname,
                "test_name": r.name,
                "total_runs": 0,
                "failures": 0,
                "passes": 0,
                "commits_with_both": set(),
                "failure_messages": [],
                "affected_commits": set(),
            }
        stats = test_stats[key]
        stats["total_runs"] += 1

        status = (r.status or "").lower()
        if status in ("failed", "error"):
            stats["failures"] += 1
            stats["affected_commits"].add(r.commit_sha)
            if r.message:
                stats["failure_messages"].append(r.message[:200])
        elif status == "passed":
            stats["passes"] += 1

    # Identify flaky tests
    detected = []
    for key, stats in test_stats.items():
        if stats["total_runs"] < min_runs:
            continue

        failure_rate = stats["failures"] / stats["total_runs"]
        # Flaky = has both passes and failures, rate between threshold and 99%
        is_flaky = (
            stats["failures"] > 0
            and stats["passes"] > 0
            and flakiness_threshold <= failure_rate < 0.99
        )

        if is_flaky:
            # Create or update flaky test record
            flaky_data = FlakyTestCreate(
                project_id=project_id,
                suite=stats["suite"],
                classname=stats["classname"],
                test_name=stats["test_name"],
                total_runs=stats["total_runs"],
                failure_count=stats["failures"],
                failure_patterns=list(set(stats["failure_messages"][:10])),
                affected_commits=list(stats["affected_commits"])[:20],
            )
            flaky = await create_flaky_test(flaky_data, db)
            detected.append(
                {
                    "id": flaky.id,
                    "test_name": stats["test_name"],
                    "classname": stats["classname"],
                    "flakiness_rate": failure_rate,
                    "total_runs": stats["total_runs"],
                    "failures": stats["failures"],
                }
            )

    return {
        "detected_count": len(detected),
        "analyzed_tests": len(test_stats),
        "flaky_tests": detected,
    }


@router.get("/flaky-tests/summary", response_model=FlakyTestSummary)
async def get_flaky_tests_summary(
    project_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get summary statistics for flaky tests."""
    res = await db.execute(select(FlakyTest).where(FlakyTest.project_id == project_id))
    all_flaky = res.scalars().all()

    active = [f for f in all_flaky if f.status == "active"]
    fixed = [f for f in all_flaky if f.status == "fixed"]
    quarantined = [f for f in all_flaky if f.status == "quarantined"]

    # Group by cause
    by_cause: Dict[str, int] = defaultdict(int)
    for f in all_flaky:
        cause = f.suspected_cause or "unknown"
        by_cause[cause] += 1

    # Get top flaky tests
    top_flaky = sorted(active, key=lambda x: x.flakiness_rate or 0, reverse=True)[:5]

    return FlakyTestSummary(
        total_flaky_tests=len(all_flaky),
        active_flaky_tests=len(active),
        fixed_this_sprint=len(fixed),
        quarantined=len(quarantined),
        by_cause=dict(by_cause),
        top_flaky_tests=top_flaky,
    )


# =============================================================================
# DELTA COVERAGE ENDPOINTS
# =============================================================================


@router.get("/coverage/delta")
async def get_delta_coverage(
    base_commit: str,
    head_commit: str,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> DeltaCoverage:
    """
    Calculate coverage delta between two commits.
    Shows which files improved/degraded and overall coverage change.
    """
    # Get base coverage
    base_res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.commit_sha == base_commit)
        .order_by(CoverageReport.created_at.desc())
    )
    base_report = base_res.scalars().first()

    # Get head coverage
    head_res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.commit_sha == head_commit)
        .order_by(CoverageReport.created_at.desc())
    )
    head_report = head_res.scalars().first()

    # Initialize result
    delta = DeltaCoverage(
        base_commit=base_commit,
        head_commit=head_commit,
    )

    if not head_report:
        return delta

    delta.current_line_coverage = head_report.line_coverage
    delta.current_branch_coverage = head_report.branch_coverage

    if base_report:
        delta.previous_line_coverage = base_report.line_coverage
        delta.previous_branch_coverage = base_report.branch_coverage
        delta.line_coverage_delta = (head_report.line_coverage or 0) - (
            base_report.line_coverage or 0
        )
        delta.branch_coverage_delta = (head_report.branch_coverage or 0) - (
            base_report.branch_coverage or 0
        )

    # Get file-level coverage for both commits
    base_files: Dict[str, Any] = {}
    if base_report:
        base_files_res = await db.execute(
            select(FileCoverage).where(FileCoverage.coverage_report_id == base_report.id)
        )
        for f in base_files_res.scalars().all():
            base_files[f.file_path] = {
                "line_coverage": f.line_coverage,
                "lines_total": f.lines_total,
            }

    head_files: Dict[str, Any] = {}
    if head_report:
        head_files_res = await db.execute(
            select(FileCoverage).where(FileCoverage.coverage_report_id == head_report.id)
        )
        for f in head_files_res.scalars().all():
            head_files[f.file_path] = {
                "line_coverage": f.line_coverage,
                "lines_total": f.lines_total,
            }

    # Calculate file-level deltas
    all_files = set(base_files.keys()) | set(head_files.keys())
    delta.total_files_changed = len(all_files)

    for file_path in all_files:
        base_cov = base_files.get(file_path, {}).get("line_coverage")
        head_cov = head_files.get(file_path, {}).get("line_coverage")

        is_new = file_path not in base_files
        is_deleted = file_path not in head_files

        if is_new and (head_cov is None or head_cov == 0):
            delta.new_files_without_coverage.append(file_path)
        elif is_deleted:
            continue  # Skip deleted files
        elif base_cov is not None and head_cov is not None:
            file_delta = head_cov - base_cov
            file_info = FileCoverageDelta(
                file_path=file_path,
                old_coverage=base_cov,
                new_coverage=head_cov,
                delta=file_delta,
                is_new_file=is_new,
            )
            if file_delta > 0.01:
                delta.files_with_increased_coverage.append(file_info)
                delta.files_improved += 1
            elif file_delta < -0.01:
                delta.files_with_decreased_coverage.append(file_info)
                delta.files_degraded += 1

    # Sort by delta magnitude
    delta.files_with_decreased_coverage.sort(key=lambda x: x.delta or 0)
    delta.files_with_increased_coverage.sort(key=lambda x: x.delta or 0, reverse=True)

    return delta


@router.get("/coverage/delta/pr/{pr_number}")
async def get_pr_delta_coverage(
    pr_number: int,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> DeltaCoverage:
    """Get coverage delta for a PR (compares latest PR commit vs base)."""
    # Get latest coverage for this PR
    res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.pr_number == pr_number)
        .order_by(CoverageReport.created_at.desc())
    )
    pr_report = res.scalars().first()

    if not pr_report:
        return DeltaCoverage(pr_number=pr_number)

    # Get previous coverage (before this PR's first commit)
    first_pr_res = await db.execute(
        select(CoverageReport)
        .where(CoverageReport.pr_number == pr_number)
        .order_by(CoverageReport.created_at.asc())
    )
    first_pr_report = first_pr_res.scalars().first()

    if first_pr_report:
        # Get coverage report just before the PR
        base_res = await db.execute(
            select(CoverageReport)
            .where(
                CoverageReport.created_at < first_pr_report.created_at,
                CoverageReport.pr_number != pr_number,
            )
            .order_by(CoverageReport.created_at.desc())
        )
        base_report = base_res.scalars().first()

        if base_report and base_report.commit_sha and pr_report.commit_sha:
            return await get_delta_coverage(
                base_commit=base_report.commit_sha,
                head_commit=pr_report.commit_sha,
                project_id=project_id,
                db=db,
            )

    # Return just current coverage if no base
    return DeltaCoverage(
        pr_number=pr_number,
        head_commit=pr_report.commit_sha,
        current_line_coverage=pr_report.line_coverage,
        current_branch_coverage=pr_report.branch_coverage,
    )


# =============================================================================
# COMPONENT COVERAGE ENDPOINTS
# =============================================================================


@router.post("/coverage/components/calculate")
async def calculate_component_coverage(
    project_id: int,
    commit_sha: Optional[str] = None,
    depth: int = 2,
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate aggregated coverage by component (directory).

    Groups file coverage by directory path at specified depth.
    E.g., depth=2 groups "src/services/auth.py" under "src/services"
    """
    # Get latest coverage report
    q = select(CoverageReport)
    if commit_sha:
        q = q.where(CoverageReport.commit_sha == commit_sha)
    q = q.order_by(CoverageReport.created_at.desc())

    res = await db.execute(q)
    report = res.scalars().first()

    if not report:
        return {"message": "No coverage report found", "components": []}

    # Get file coverage
    files_res = await db.execute(
        select(FileCoverage).where(FileCoverage.coverage_report_id == report.id)
    )
    files = files_res.scalars().all()

    # Group by component path
    components: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "total_lines": 0,
            "covered_lines": 0,
            "total_files": 0,
            "covered_files": 0,
            "file_coverages": [],
        }
    )

    for f in files:
        # Extract component path at specified depth
        parts = f.file_path.split("/")
        component_path = "/".join(parts[:depth]) if len(parts) > depth else parts[0]

        comp = components[component_path]
        comp["total_files"] += 1
        comp["total_lines"] += f.lines_total or 0
        comp["covered_lines"] += f.lines_covered or 0
        comp["file_coverages"].append(f.line_coverage or 0)

        if (f.line_coverage or 0) > 0:
            comp["covered_files"] += 1

    # Create component coverage records
    created = []
    for path, data in components.items():
        line_coverage = (
            data["covered_lines"] / data["total_lines"] if data["total_lines"] > 0 else 0
        )

        # Calculate risk score (lower coverage = higher risk)
        risk_score = max(0, 1.0 - line_coverage)
        priority = (
            "critical"
            if risk_score > 0.5
            else "high"
            if risk_score > 0.3
            else "medium"
            if risk_score > 0.15
            else "low"
        )

        comp_data = ComponentCoverageCreate(
            project_id=project_id,
            coverage_report_id=report.id,
            component_path=path,
            line_coverage=line_coverage,
            total_files=data["total_files"],
            covered_files=data["covered_files"],
            total_lines=data["total_lines"],
            covered_lines=data["covered_lines"],
            risk_score=risk_score,
            priority=priority,
            commit_sha=report.commit_sha,
        )

        comp_record = ComponentCoverage(
            project_id=comp_data.project_id,
            coverage_report_id=comp_data.coverage_report_id,
            component_path=comp_data.component_path,
            line_coverage=comp_data.line_coverage,
            total_files=comp_data.total_files,
            covered_files=comp_data.covered_files,
            total_lines=comp_data.total_lines,
            covered_lines=comp_data.covered_lines,
            risk_score=comp_data.risk_score,
            priority=comp_data.priority,
            commit_sha=comp_data.commit_sha,
        )
        db.add(comp_record)
        created.append(
            {
                "component_path": path,
                "line_coverage": line_coverage,
                "total_files": data["total_files"],
                "total_lines": data["total_lines"],
                "risk_score": risk_score,
                "priority": priority,
            }
        )

    await db.commit()

    return {
        "commit_sha": report.commit_sha,
        "total_components": len(created),
        "components": sorted(created, key=lambda x: x["risk_score"], reverse=True),
    }


@router.get("/coverage/components", response_model=List[ComponentCoverageSchema])
async def list_component_coverage(
    project_id: int,
    commit_sha: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List component coverage for a project with pagination."""
    q = select(ComponentCoverage).where(ComponentCoverage.project_id == project_id)
    if commit_sha:
        q = q.where(ComponentCoverage.commit_sha == commit_sha)
    q = q.order_by(ComponentCoverage.risk_score.desc()).offset(skip).limit(limit)

    res = await db.execute(q)
    return res.scalars().all()


@router.get("/coverage/components/summary", response_model=ComponentCoverageSummary)
async def get_component_coverage_summary(
    project_id: int,
    threshold: float = 0.8,
    db: AsyncSession = Depends(get_db),
):
    """Get summary of component coverage with risk assessment."""
    # Get latest components
    res = await db.execute(
        select(ComponentCoverage)
        .where(ComponentCoverage.project_id == project_id)
        .order_by(ComponentCoverage.created_at.desc())
    )
    all_components = res.scalars().all()

    if not all_components:
        return ComponentCoverageSummary()

    # Get unique components (latest per path)
    unique: Dict[str, ComponentCoverage] = {}
    for c in all_components:
        if c.component_path not in unique:
            unique[c.component_path] = c

    components = list(unique.values())

    above_threshold = [c for c in components if (c.line_coverage or 0) >= threshold]
    below_threshold = [c for c in components if (c.line_coverage or 0) < threshold]
    critical_risk = [c for c in components if c.priority == "critical"]
    high_risk = [c for c in components if c.priority == "high"]

    avg_coverage = (
        sum(c.line_coverage or 0 for c in components) / len(components) if components else 0
    )

    return ComponentCoverageSummary(
        total_components=len(components),
        components_above_threshold=len(above_threshold),
        components_below_threshold=len(below_threshold),
        average_coverage=avg_coverage,
        critical_risk_components=critical_risk[:5],
        high_risk_components=high_risk[:5],
        components=sorted(components, key=lambda x: x.risk_score or 0, reverse=True),
    )


# =============================================================================
# COVERAGE TREND ENDPOINTS
# =============================================================================


@router.get("/coverage/trend", response_model=CoverageTrend)
async def get_coverage_trend(
    project_id: int,
    period: str = "30d",
    db: AsyncSession = Depends(get_db),
):
    """Get coverage trend over time."""
    days = int(period.replace("d", "")) if "d" in period else 30
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Get coverage history
    res = await db.execute(
        select(CoverageHistory)
        .where(
            CoverageHistory.project_id == project_id,
            CoverageHistory.date >= cutoff,
        )
        .order_by(CoverageHistory.date.asc())
    )
    history = res.scalars().all()

    # If no history, try to build from coverage reports
    if not history:
        reports_res = await db.execute(
            select(CoverageReport)
            .where(CoverageReport.created_at >= cutoff)
            .order_by(CoverageReport.created_at.asc())
        )
        reports = reports_res.scalars().all()

        # Filter by project
        allowed_shas = await _filter_commits_by_project(reports, project_id, db)
        if allowed_shas is not None:
            reports = [r for r in reports if r.commit_sha in allowed_shas]

        data_points = [
            CoverageTrendPoint(
                date=r.created_at,
                line_coverage=r.line_coverage,
                branch_coverage=r.branch_coverage,
            )
            for r in reports
        ]
    else:
        data_points = [
            CoverageTrendPoint(
                date=h.date,
                line_coverage=h.line_coverage,
                branch_coverage=h.branch_coverage,
                test_pass_rate=h.test_pass_rate,
                flaky_test_count=h.flaky_tests,
            )
            for h in history
        ]

    # Calculate trend direction
    coverage_change = 0.0
    direction = "stable"
    if len(data_points) >= 2:
        first_cov = data_points[0].line_coverage or 0
        last_cov = data_points[-1].line_coverage or 0
        coverage_change = last_cov - first_cov
        if coverage_change > 0.02:
            direction = "improving"
        elif coverage_change < -0.02:
            direction = "degrading"

    # Find milestones
    highest = max(data_points, key=lambda x: x.line_coverage or 0) if data_points else None
    lowest = min(data_points, key=lambda x: x.line_coverage or 0) if data_points else None

    return CoverageTrend(
        project_id=project_id,
        period=period,
        data_points=data_points,
        coverage_change=coverage_change,
        coverage_direction=direction,
        highest_coverage=highest,
        lowest_coverage=lowest,
    )


@router.post("/coverage/history/record")
async def record_coverage_history(
    data: CoverageHistoryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Record a coverage history point (used for aggregation)."""
    history = CoverageHistory(
        project_id=data.project_id,
        sprint_id=data.sprint_id,
        date=data.date,
        period_type=data.period_type.value,
        line_coverage=data.line_coverage,
        branch_coverage=data.branch_coverage,
        function_coverage=data.function_coverage,
        statement_coverage=data.statement_coverage,
        line_coverage_delta=data.line_coverage_delta,
        branch_coverage_delta=data.branch_coverage_delta,
        total_lines=data.total_lines,
        covered_lines=data.covered_lines,
        total_branches=data.total_branches,
        covered_branches=data.covered_branches,
        total_tests=data.total_tests,
        passed_tests=data.passed_tests,
        failed_tests=data.failed_tests,
        skipped_tests=data.skipped_tests,
        flaky_tests=data.flaky_tests,
        test_pass_rate=data.test_pass_rate,
        commit_sha=data.commit_sha,
        pr_number=data.pr_number,
    )
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return {"id": history.id, "date": history.date}


# =============================================================================
# TEST ANALYTICS DASHBOARD
# =============================================================================


@router.get("/analytics/dashboard", response_model=TestAnalyticsDashboard)
async def get_test_analytics_dashboard(
    project_id: int,
    sprint_id: Optional[int] = None,
    coverage_target: float = 0.8,
    db: AsyncSession = Depends(get_db),
):
    """Get complete test analytics dashboard."""
    # Get latest coverage
    reports_res = await db.execute(
        select(CoverageReport).order_by(CoverageReport.created_at.desc()).limit(50)
    )
    reports = reports_res.scalars().all()

    allowed_shas = await _filter_commits_by_project(reports, project_id, db)
    project_reports = (
        [r for r in reports if r.commit_sha in allowed_shas]
        if allowed_shas is not None
        else reports
    )

    latest_report = project_reports[0] if project_reports else None

    # Get test results summary
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    tests_res = await db.execute(select(TestResult).where(TestResult.created_at >= cutoff))
    tests = tests_res.scalars().all()
    if allowed_shas is not None:
        tests = [t for t in tests if t.commit_sha in allowed_shas]

    passing = len([t for t in tests if (t.status or "").lower() == "passed"])
    failing = len([t for t in tests if (t.status or "").lower() in ("failed", "error")])
    skipped = len([t for t in tests if (t.status or "").lower() == "skipped"])
    total_tests = len(tests)
    test_pass_rate = passing / total_tests if total_tests > 0 else 0

    # Get flaky summary
    flaky_summary = await get_flaky_tests_summary(project_id, db)

    # Get component summary
    component_summary = await get_component_coverage_summary(
        project_id, threshold=coverage_target, db=db
    )

    # Get coverage trend
    coverage_trend = await get_coverage_trend(project_id, period="30d", db=db)

    # Get latest delta (if there's a recent PR)
    latest_delta = None
    if latest_report and latest_report.pr_number:
        latest_delta = await get_pr_delta_coverage(latest_report.pr_number, project_id, db)

    current_coverage = latest_report.line_coverage if latest_report else None
    coverage_met = (current_coverage or 0) >= coverage_target

    return TestAnalyticsDashboard(
        project_id=project_id,
        sprint_id=sprint_id,
        current_line_coverage=current_coverage,
        current_branch_coverage=latest_report.branch_coverage if latest_report else None,
        coverage_target=coverage_target,
        coverage_met=coverage_met,
        total_tests=total_tests,
        passing_tests=passing,
        failing_tests=failing,
        skipped_tests=skipped,
        test_pass_rate=test_pass_rate,
        flaky_summary=flaky_summary,
        component_summary=component_summary,
        coverage_trend=coverage_trend,
        latest_delta=latest_delta,
    )
