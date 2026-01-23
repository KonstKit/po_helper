from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from enum import Enum


class SeverityLevel(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class DefectStatus(str, Enum):
    open = "open"
    investigating = "investigating"
    resolved = "resolved"
    closed = "closed"


class RootCause(str, Enum):
    missing_test = "missing_test"
    edge_case = "edge_case"
    integration = "integration"
    regression = "regression"
    environment = "environment"
    configuration = "configuration"
    third_party = "third_party"
    unknown = "unknown"


# === Escaped Defect Schemas ===


class EscapedDefectBase(BaseModel):
    title: str
    description: Optional[str] = None
    external_id: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.medium
    priority: Optional[str] = None
    environment: str = "production"
    root_cause: Optional[RootCause] = None
    affected_component: Optional[str] = None
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    time_to_detect_hours: Optional[float] = None
    time_to_resolve_hours: Optional[float] = None
    fix_commit_sha: Optional[str] = None
    fix_pr_number: Optional[int] = None
    customers_affected: Optional[int] = None
    revenue_impact: Optional[float] = None
    status: DefectStatus = DefectStatus.open


class EscapedDefectCreate(EscapedDefectBase):
    project_id: int
    sprint_id: Optional[int] = None


class EscapedDefectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[SeverityLevel] = None
    priority: Optional[str] = None
    root_cause: Optional[RootCause] = None
    affected_component: Optional[str] = None
    resolved_at: Optional[datetime] = None
    time_to_resolve_hours: Optional[float] = None
    fix_commit_sha: Optional[str] = None
    fix_pr_number: Optional[int] = None
    customers_affected: Optional[int] = None
    revenue_impact: Optional[float] = None
    status: Optional[DefectStatus] = None


class EscapedDefect(EscapedDefectBase):
    id: int
    project_id: int
    sprint_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# === Defect Metrics Schemas ===


class DefectMetricsBase(BaseModel):
    period_start: datetime
    period_end: datetime
    total_defects: int = 0
    defects_found_in_dev: int = 0
    defects_found_in_qa: int = 0
    defects_found_in_prod: int = 0
    critical_defects: int = 0
    high_defects: int = 0
    medium_defects: int = 0
    low_defects: int = 0
    defect_density: Optional[float] = None
    defect_removal_efficiency: Optional[float] = None
    escape_rate: Optional[float] = None
    mean_time_to_resolve_hours: Optional[float] = None
    mean_time_to_detect_hours: Optional[float] = None
    lines_of_code: Optional[int] = None
    code_churn: Optional[int] = None
    test_automation_percent: Optional[float] = None
    test_pass_rate: Optional[float] = None


class DefectMetricsCreate(DefectMetricsBase):
    project_id: int
    sprint_id: Optional[int] = None


class DefectMetrics(DefectMetricsBase):
    id: int
    project_id: int
    sprint_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# === Quality Summary Schemas (Computed) ===


class QualitySummary(BaseModel):
    """Summary of quality metrics for a project or sprint."""

    project_id: int
    sprint_id: Optional[int] = None

    # Defect overview
    total_escaped_defects: int = 0
    open_defects: int = 0
    resolved_defects: int = 0

    # By severity
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0

    # Key metrics
    defect_density: Optional[float] = Field(None, description="Defects per KLOC")
    defect_removal_efficiency: Optional[float] = Field(None, description="DRE percentage")
    escape_rate: Optional[float] = Field(None, description="% of defects escaping to prod")
    mttr_hours: Optional[float] = Field(None, description="Mean Time To Resolve")
    mttd_hours: Optional[float] = Field(None, description="Mean Time To Detect")

    # Trend
    trend_direction: Optional[str] = None  # improving, stable, declining
    trend_change_percent: Optional[float] = None


class DefectTrend(BaseModel):
    """Trend data point for defect tracking."""

    date: datetime
    total_defects: int
    escaped_defects: int
    resolved_defects: int
    dre: Optional[float] = None


class QualityTrendData(BaseModel):
    """Quality metrics trend over time."""

    project_id: int
    trends: List[DefectTrend]
    period_days: int


class RootCauseAnalysis(BaseModel):
    """Root cause breakdown for defects."""

    root_cause: str
    count: int
    percentage: float
    avg_time_to_resolve_hours: Optional[float] = None


class ComponentAnalysis(BaseModel):
    """Defect analysis by component."""

    component: str
    defect_count: int
    critical_count: int
    avg_severity_score: float  # 4=critical, 3=high, 2=medium, 1=low


class QualityDashboard(BaseModel):
    """Complete quality dashboard data."""

    summary: QualitySummary
    recent_defects: List[EscapedDefect]
    root_cause_breakdown: List[RootCauseAnalysis]
    component_analysis: List[ComponentAnalysis]
    trend_data: QualityTrendData


# === Sprint Quality Report Schemas ===


class ReportFormat(str, Enum):
    pdf = "pdf"
    excel = "excel"
    json = "json"
    csv = "csv"


class ReportSection(str, Enum):
    executive_summary = "executive_summary"
    quality_metrics = "quality_metrics"
    test_coverage = "test_coverage"
    flaky_tests = "flaky_tests"
    escaped_defects = "escaped_defects"
    pr_quality = "pr_quality"
    component_health = "component_health"
    trends = "trends"
    recommendations = "recommendations"


class TestCoverageSection(BaseModel):
    """Test coverage data for reports."""

    line_coverage: Optional[float] = None
    branch_coverage: Optional[float] = None
    function_coverage: Optional[float] = None
    coverage_target: float = 0.8
    coverage_met: bool = False
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    test_pass_rate: float = 0.0
    flaky_test_count: int = 0


class PRQualitySection(BaseModel):
    """PR quality gate data for reports."""

    total_prs_merged: int = 0
    prs_meeting_gates: int = 0
    gate_pass_rate: float = 0.0
    avg_review_time_hours: Optional[float] = None
    avg_approvals: Optional[float] = None
    prs_with_tests: int = 0
    prs_with_coverage: int = 0


class ComponentHealthItem(BaseModel):
    """Health status for a component."""

    component: str
    coverage: Optional[float] = None
    defect_count: int = 0
    flaky_test_count: int = 0
    risk_score: float = 0.0
    priority: str = "medium"


class RecommendationItem(BaseModel):
    """Actionable recommendation for quality improvement."""

    category: str  # coverage, testing, defects, etc.
    priority: str  # critical, high, medium, low
    recommendation: str
    impact: str
    effort: str  # low, medium, high


class SprintQualityReport(BaseModel):
    """Complete sprint quality report."""

    # Metadata
    report_id: Optional[str] = None
    project_id: int
    project_name: Optional[str] = None
    sprint_id: Optional[int] = None
    sprint_name: Optional[str] = None
    report_date: datetime
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None

    # Executive Summary
    overall_quality_score: float = 0.0  # 0-100
    quality_grade: str = "C"  # A, B, C, D, F
    key_highlights: List[str] = []
    key_concerns: List[str] = []

    # Quality Metrics Section
    quality_summary: Optional[QualitySummary] = None

    # Test Coverage Section
    test_coverage: Optional[TestCoverageSection] = None

    # PR Quality Section
    pr_quality: Optional[PRQualitySection] = None

    # Escaped Defects Summary
    escaped_defects_summary: Optional[dict] = None
    recent_escaped_defects: List[EscapedDefect] = []

    # Component Health
    component_health: List[ComponentHealthItem] = []

    # Trends
    coverage_trend: List[dict] = []
    defect_trend: List[dict] = []

    # Recommendations
    recommendations: List[RecommendationItem] = []


class ReportGenerationRequest(BaseModel):
    """Request to generate a quality report."""

    project_id: int
    sprint_id: Optional[int] = None
    format: ReportFormat = ReportFormat.pdf
    sections: List[ReportSection] = [
        ReportSection.executive_summary,
        ReportSection.quality_metrics,
        ReportSection.test_coverage,
        ReportSection.escaped_defects,
        ReportSection.recommendations,
    ]
    include_charts: bool = True
    include_details: bool = True


class ReportGenerationResponse(BaseModel):
    """Response after report generation."""

    success: bool
    report_id: Optional[str] = None
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    format: ReportFormat
    generated_at: datetime
    file_size_bytes: Optional[int] = None
    error: Optional[str] = None
