"""Pydantic schemas for testing and coverage analytics."""

from datetime import datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict


# Enums
class FlakyTestStatus(str, Enum):
    active = "active"
    fixed = "fixed"
    ignored = "ignored"
    quarantined = "quarantined"


class FlakyTestCause(str, Enum):
    race_condition = "race_condition"
    timing = "timing"
    environment = "environment"
    external_dependency = "external_dependency"
    data_dependency = "data_dependency"
    resource_leak = "resource_leak"
    unknown = "unknown"


class PeriodType(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"


class CoveragePriority(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


# Flaky Test Schemas
class FlakyTestBase(BaseModel):
    suite: Optional[str] = None
    classname: Optional[str] = None
    test_name: str
    status: FlakyTestStatus = FlakyTestStatus.active
    suspected_cause: Optional[FlakyTestCause] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = None


class FlakyTestCreate(FlakyTestBase):
    project_id: int
    total_runs: int = 0
    failure_count: int = 0
    failure_patterns: Optional[List[str]] = None
    affected_commits: Optional[List[str]] = None


class FlakyTestUpdate(BaseModel):
    status: Optional[FlakyTestStatus] = None
    suspected_cause: Optional[FlakyTestCause] = None
    assigned_to: Optional[str] = None
    fix_pr_number: Optional[int] = None
    notes: Optional[str] = None


class FlakyTest(FlakyTestBase):
    id: int
    project_id: int
    total_runs: int
    failure_count: int
    flakiness_rate: Optional[float] = None
    last_failure_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    first_detected_at: Optional[datetime] = None
    failure_patterns: Optional[List[str]] = None
    affected_commits: Optional[List[str]] = None
    fix_pr_number: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Coverage History Schemas
class CoverageHistoryBase(BaseModel):
    project_id: int
    sprint_id: Optional[int] = None
    date: datetime
    period_type: PeriodType = PeriodType.daily


class CoverageHistoryCreate(CoverageHistoryBase):
    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    function_coverage: Optional[float] = None
    statement_coverage: Optional[float] = None
    line_coverage_delta: Optional[float] = None
    branch_coverage_delta: Optional[float] = None
    total_lines: Optional[int] = None
    covered_lines: Optional[int] = None
    total_branches: Optional[int] = None
    covered_branches: Optional[int] = None
    total_tests: Optional[int] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    skipped_tests: Optional[int] = None
    flaky_tests: Optional[int] = None
    test_pass_rate: Optional[float] = None
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None


class CoverageHistory(CoverageHistoryBase):
    id: int
    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    function_coverage: Optional[float] = None
    statement_coverage: Optional[float] = None
    line_coverage_delta: Optional[float] = None
    branch_coverage_delta: Optional[float] = None
    total_lines: Optional[int] = None
    covered_lines: Optional[int] = None
    total_branches: Optional[int] = None
    covered_branches: Optional[int] = None
    total_tests: Optional[int] = None
    passed_tests: Optional[int] = None
    failed_tests: Optional[int] = None
    skipped_tests: Optional[int] = None
    flaky_tests: Optional[int] = None
    test_pass_rate: Optional[float] = None
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Component Coverage Schemas
class ComponentCoverageBase(BaseModel):
    project_id: int
    component_path: str
    component_name: Optional[str] = None


class ComponentCoverageCreate(ComponentCoverageBase):
    coverage_report_id: Optional[int] = None
    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    function_coverage: Optional[float] = None
    total_files: Optional[int] = None
    covered_files: Optional[int] = None
    total_lines: Optional[int] = None
    covered_lines: Optional[int] = None
    average_complexity: Optional[float] = None
    max_complexity: Optional[float] = None
    risk_score: Optional[float] = None
    priority: Optional[CoveragePriority] = None
    commit_sha: Optional[str] = None


class ComponentCoverage(ComponentCoverageBase):
    id: int
    coverage_report_id: Optional[int] = None
    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    function_coverage: Optional[float] = None
    total_files: Optional[int] = None
    covered_files: Optional[int] = None
    total_lines: Optional[int] = None
    covered_lines: Optional[int] = None
    average_complexity: Optional[float] = None
    max_complexity: Optional[float] = None
    risk_score: Optional[float] = None
    priority: Optional[CoveragePriority] = None
    commit_sha: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# Delta Coverage Schemas
class FileCoverageDelta(BaseModel):
    """Coverage change for a single file between two commits."""

    file_path: str
    old_coverage: Optional[float] = None
    new_coverage: Optional[float] = None
    delta: Optional[float] = None
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None
    is_new_file: bool = False
    is_deleted_file: bool = False


class DeltaCoverage(BaseModel):
    """Overall coverage delta between two commits/PRs."""

    base_commit: Optional[str] = None
    head_commit: Optional[str] = None
    pr_number: Optional[int] = None

    # Overall delta
    line_coverage_delta: float = 0.0
    branch_coverage_delta: float = 0.0

    # Current values
    current_line_coverage: Optional[float] = None
    current_branch_coverage: Optional[float] = None

    # Previous values
    previous_line_coverage: Optional[float] = None
    previous_branch_coverage: Optional[float] = None

    # File-level changes
    files_with_decreased_coverage: List[FileCoverageDelta] = []
    files_with_increased_coverage: List[FileCoverageDelta] = []
    new_files_without_coverage: List[str] = []

    # Summary
    total_files_changed: int = 0
    files_improved: int = 0
    files_degraded: int = 0


# Aggregated Analytics Schemas
class FlakyTestSummary(BaseModel):
    """Summary of flaky tests in the project."""

    total_flaky_tests: int = 0
    active_flaky_tests: int = 0
    fixed_this_sprint: int = 0
    quarantined: int = 0

    # By cause
    by_cause: dict = Field(default_factory=dict)

    # Trend
    trend_direction: str = "stable"  # improving, degrading, stable
    trend_percent: float = 0.0

    # Most flaky
    top_flaky_tests: List[FlakyTest] = []


class ComponentCoverageSummary(BaseModel):
    """Summary of coverage by component."""

    total_components: int = 0
    components_above_threshold: int = 0
    components_below_threshold: int = 0
    average_coverage: float = 0.0

    # Risk assessment
    critical_risk_components: List[ComponentCoverage] = []
    high_risk_components: List[ComponentCoverage] = []

    # All components sorted by priority
    components: List[ComponentCoverage] = []


class CoverageTrendPoint(BaseModel):
    """Single point in coverage trend."""

    date: datetime
    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    test_pass_rate: Optional[float] = None
    flaky_test_count: Optional[int] = None


class CoverageTrend(BaseModel):
    """Coverage trend over time."""

    project_id: int
    period: str  # "7d", "30d", "90d"
    data_points: List[CoverageTrendPoint] = []

    # Summary
    coverage_change: float = 0.0
    coverage_direction: str = "stable"  # improving, degrading, stable

    # Milestones
    highest_coverage: Optional[CoverageTrendPoint] = None
    lowest_coverage: Optional[CoverageTrendPoint] = None


class TestAnalyticsDashboard(BaseModel):
    """Complete test analytics dashboard data."""

    project_id: int
    sprint_id: Optional[int] = None

    # Current coverage
    current_line_coverage: Optional[float] = None
    current_branch_coverage: Optional[float] = None
    coverage_target: float = 0.8
    coverage_met: bool = False

    # Test summary
    total_tests: int = 0
    passing_tests: int = 0
    failing_tests: int = 0
    skipped_tests: int = 0
    test_pass_rate: float = 0.0

    # Flaky tests
    flaky_summary: FlakyTestSummary = Field(default_factory=FlakyTestSummary)

    # Component coverage
    component_summary: ComponentCoverageSummary = Field(default_factory=ComponentCoverageSummary)

    # Trends
    coverage_trend: CoverageTrend = Field(
        default_factory=lambda: CoverageTrend(project_id=0, period="30d")
    )

    # Recent delta (from latest PR/commit)
    latest_delta: Optional[DeltaCoverage] = None
