from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils.confidence import normalize_confidence as _normalize_confidence


class ArtifactBase(BaseModel):
    tenant_id: Optional[str] = None
    project_id: Optional[int] = None
    created_by_id: Optional[int] = None
    type: str
    source: str
    external_id: str
    source_system: Optional[str] = None
    source_reference_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None
    display_key: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    version: int = 1
    parent_version_id: Optional[int] = None


class ArtifactCreate(ArtifactBase):
    pass


class ArtifactInDB(ArtifactBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Artifact(ArtifactInDB):
    pass


class ArtifactLinkBase(BaseModel):
    tenant_id: Optional[str] = None
    project_id: Optional[int] = None
    created_by_id: Optional[int] = None
    created_via: Optional[str] = None
    source_system: Optional[str] = None
    source_reference_id: Optional[str] = None
    method: Optional[str] = None
    from_artifact_id: int
    to_artifact_id: int
    link_type: str
    confidence: Optional[float] = None
    confidence_factors: Optional[Dict[str, Any]] = None


class ArtifactLinkCreate(ArtifactLinkBase):
    pass


class ArtifactLinkInDB(ArtifactLinkBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence_scale(cls, v: Optional[float]) -> Optional[float]:
        """Normalize legacy 0..100 confidence to 0..1 scale."""
        return _normalize_confidence(v)


class ArtifactLink(ArtifactLinkInDB):
    pass


class SuggestedLinkBase(BaseModel):
    tenant_id: Optional[str] = None
    project_id: Optional[int] = None
    from_artifact_id: int
    to_artifact_id: int
    suggested_link_type: str
    similarity_score: float
    method: str
    reason: Optional[str] = None
    status: str = "pending"
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = None


class SuggestedLinkInDB(SuggestedLinkBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SuggestedLink(SuggestedLinkInDB):
    pass


class BaselineBase(BaseModel):
    project_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    filters_json: Optional[Dict[str, Any]] = None
    created_by_id: Optional[int] = None


class BaselineInDB(BaselineBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Baseline(BaselineInDB):
    pass


class BaselineItemBase(BaseModel):
    baseline_id: int
    artifact_id: Optional[int] = None
    link_id: Optional[int] = None


class BaselineItemCreate(BaselineItemBase):
    @model_validator(mode="after")
    def validate_exactly_one_target(self):
        has_artifact = self.artifact_id is not None
        has_link = self.link_id is not None
        if has_artifact == has_link:
            raise ValueError("Exactly one of artifact_id or link_id must be provided")
        return self


class BaselineItemInDB(BaselineItemBase):
    id: int
    included_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BaselineItem(BaselineItemInDB):
    pass


class BaselineCompareRequest(BaseModel):
    baseline_id: int = Field(description="Baseline to compare from")
    against_baseline_id: int = Field(description="Baseline to compare against")


class BaselineCompareSummary(BaseModel):
    added_artifacts: int = 0
    removed_artifacts: int = 0
    added_links: int = 0
    removed_links: int = 0
    total_added: int = 0
    total_removed: int = 0


class BaselineCompareResponse(BaseModel):
    baseline_id: int
    against_baseline_id: int
    baseline_name: str
    against_baseline_name: str
    project_id: Optional[int] = None
    against_project_id: Optional[int] = None
    summary: BaselineCompareSummary
    added_artifact_ids: List[int] = Field(default_factory=list)
    removed_artifact_ids: List[int] = Field(default_factory=list)
    added_link_ids: List[int] = Field(default_factory=list)
    removed_link_ids: List[int] = Field(default_factory=list)


class BaselineExportItem(BaseModel):
    item_id: int
    item_type: Literal["artifact", "link", "empty"]
    artifact_id: Optional[int] = None
    link_id: Optional[int] = None
    included_at: datetime


BaselineExportFormat = Literal["json", "csv"]


class BaselineExportResponse(BaseModel):
    format: BaselineExportFormat = Field(default="json")
    baseline: Baseline
    exported_at: datetime
    item_count: int = 0
    artifact_ids: List[int] = Field(default_factory=list)
    link_ids: List[int] = Field(default_factory=list)
    items: List[BaselineExportItem] = Field(default_factory=list)


class ProjectionBase(BaseModel):
    project_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    filters_json: Optional[Dict[str, Any]] = None
    created_by_id: Optional[int] = None


class ProjectionInDB(ProjectionBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Projection(ProjectionInDB):
    pass


class ProjectionItemBase(BaseModel):
    projection_id: int
    artifact_id: Optional[int] = None
    link_id: Optional[int] = None


class ProjectionItemInDB(ProjectionItemBase):
    id: int
    included_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectionItem(ProjectionItemInDB):
    pass


class SyncTaskBase(BaseModel):
    source_id: Optional[int] = None
    project_id: Optional[int] = None
    rule_id: Optional[int] = None
    task_type: str
    status: str
    started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    cursor_in: Optional[str] = None
    cursor_out: Optional[str] = None
    item_counts: Optional[Dict[str, Any]] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    trigger: Optional[str] = None


class SyncTaskInDB(SyncTaskBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncTask(SyncTaskInDB):
    pass


class SyncTaskRecoveryResult(BaseModel):
    recovered: int = 0
    project_id: Optional[int] = None
    task_id: Optional[int] = None
    all: bool = False
    ttl_seconds: Optional[int] = None


class AuditLogBase(BaseModel):
    tenant_id: Optional[str] = None
    project_id: Optional[int] = None
    actor_id: Optional[int] = None
    action: str
    entity_type: str
    entity_id: int
    request_id: Optional[str] = None
    outcome: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class AuditLogInDB(AuditLogBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLog(AuditLogInDB):
    pass


class ConnectorConfigSettings(BaseModel):
    """Known keys for ConnectorConfig.settings_json (provider-specific extras allowed)."""

    base_url: Optional[str] = Field(
        default=None,
        description="Override base URL for the provider (e.g., https://jira.company.com).",
    )
    api_token: Optional[str] = Field(
        default=None,
        description="Override token/PAT for the provider (stored encrypted in settings_json).",
    )
    email: Optional[str] = Field(
        default=None,
        description="Email for Basic auth (Jira/Confluence); optional for PAT mode.",
    )
    use_pat: Optional[bool] = Field(
        default=None,
        description="Force PAT/Bearer auth when supported (Jira/Confluence).",
    )
    rate_limit_rps: Optional[float] = Field(
        default=None, description="Rate limit in requests per second."
    )
    rate_limit_per_minute: Optional[int] = Field(
        default=None, description="Rate limit in requests per minute."
    )
    rate_limit_burst: Optional[int] = Field(
        default=None, description="Allowed burst size above steady rate."
    )
    retry_after_header: Optional[bool] = Field(
        default=None, description="Honor Retry-After header when present."
    )
    request_timeout_seconds: Optional[int] = Field(
        default=None, description="HTTP request timeout override in seconds."
    )
    max_retries: Optional[int] = Field(
        default=None, description="Max retry attempts for transient failures."
    )
    backoff_base_seconds: Optional[float] = Field(
        default=None, description="Base delay for exponential backoff."
    )
    backoff_max_seconds: Optional[float] = Field(
        default=None, description="Max delay for exponential backoff."
    )

    model_config = ConfigDict(extra="allow")


class ConnectorConfigBase(BaseModel):
    project_id: Optional[int] = None
    provider: str
    is_enabled: bool = True
    settings_json: Optional[ConnectorConfigSettings] = Field(
        default=None, description="Provider-specific overrides and rate-limit policy knobs."
    )
    auth_ref: Optional[str] = None
    rate_limit_policy: Optional[str] = None


class ConnectorConfigInDB(ConnectorConfigBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ConnectorConfig(ConnectorConfigInDB):
    pass


# =============================================================================
# RTM Matrix Schemas
# =============================================================================


class RTMFilters(BaseModel):
    """Filtering options for RTM matrix query."""

    row_types: Optional[List[str]] = Field(
        default=None, description="Artifact types for rows (e.g., ['requirement', 'jira_issue'])"
    )
    col_types: Optional[List[str]] = Field(
        default=None, description="Artifact types for columns (e.g., ['test_case', 'commit'])"
    )
    row_statuses: Optional[List[str]] = Field(
        default=None, description="Filter rows by status (e.g., ['Open', 'In Progress'])"
    )
    col_statuses: Optional[List[str]] = Field(
        default=None, description="Filter columns by status"
    )
    link_types: Optional[List[str]] = Field(
        default=None,
        description="Link types to include (e.g., ['implements', 'tests'])",
    )
    min_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Minimum confidence threshold for links"
    )
    search_query: Optional[str] = Field(
        default=None, description="Text search in artifact titles"
    )
    direction: str = Field(
        default="both",
        description="Link direction: 'outgoing', 'incoming', or 'both'",
    )
    include_orphans: bool = Field(
        default=False, description="Include artifacts without links"
    )


class RTMPagination(BaseModel):
    """Pagination parameters for RTM matrix."""

    row_skip: int = Field(default=0, ge=0, description="Skip N rows")
    row_limit: int = Field(default=50, ge=1, le=500, description="Max rows to return")
    col_skip: int = Field(default=0, ge=0, description="Skip N columns")
    col_limit: int = Field(default=50, ge=1, le=500, description="Max columns to return")


class ArtifactSummary(BaseModel):
    """Lightweight artifact representation for matrix cells."""

    id: int
    type: str
    source: str
    external_id: str
    display_key: Optional[str] = None
    title: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class RTMCell(BaseModel):
    """Single cell in the RTM matrix representing link(s) between artifacts."""

    has_link: bool = False
    link_count: int = 0
    link_types: List[str] = Field(default_factory=list)
    avg_confidence: Optional[float] = None
    links: Optional[List[Dict[str, Any]]] = Field(
        default=None, description="Detailed link info when requested"
    )


class RTMMatrixResponse(BaseModel):
    """Full RTM matrix response with rows, columns, and cells."""

    rows: List[ArtifactSummary] = Field(description="Row artifacts")
    columns: List[ArtifactSummary] = Field(description="Column artifacts")
    cells: Dict[str, Dict[str, RTMCell]] = Field(
        description="Matrix cells indexed by row_id:col_id"
    )
    total_rows: int = Field(description="Total number of rows (before pagination)")
    total_columns: int = Field(description="Total number of columns (before pagination)")
    coverage: Dict[str, Any] = Field(description="Coverage statistics")
    filters_applied: Dict[str, Any] = Field(description="Filters that were applied")

    model_config = ConfigDict(from_attributes=True)


class CoverageStats(BaseModel):
    """Coverage statistics for a set of artifacts."""

    total_artifacts: int = 0
    linked_artifacts: int = 0
    unlinked_artifacts: int = 0
    coverage_pct: float = 0.0
    by_type: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    by_link_type: Dict[str, int] = Field(default_factory=dict)


class CoverageAnalyticsResponse(BaseModel):
    """Response for coverage analytics endpoint."""

    project_id: Optional[int] = None
    coverage: CoverageStats
    uncovered_requirements: List[ArtifactSummary] = Field(default_factory=list)
    gap_analysis: Dict[str, Any] = Field(default_factory=dict)
    trends: Optional[Dict[str, Any]] = None
    quality_gates: Dict[str, bool] = Field(default_factory=dict)
    generated_at: datetime


# =============================================================================
# Matrix Config (Saved Projections) Schemas
# =============================================================================


class MatrixConfigBase(BaseModel):
    """Base schema for saved matrix configurations."""

    project_id: Optional[int] = None
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    filters: Optional[RTMFilters] = None
    pagination: Optional[RTMPagination] = None
    display_options: Optional[Dict[str, Any]] = Field(
        default=None, description="UI display preferences (column order, grouping, etc.)"
    )
    is_default: bool = Field(default=False, description="Use as default view for project")


class MatrixConfigCreate(MatrixConfigBase):
    """Schema for creating a matrix configuration."""

    pass


class MatrixConfigUpdate(BaseModel):
    """Schema for updating a matrix configuration."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    filters: Optional[RTMFilters] = None
    pagination: Optional[RTMPagination] = None
    display_options: Optional[Dict[str, Any]] = None
    is_default: Optional[bool] = None


class MatrixConfigInDB(MatrixConfigBase):
    """Schema for matrix configuration from database."""

    id: int
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MatrixConfig(MatrixConfigInDB):
    """Schema for matrix configuration response."""

    pass


# =============================================================================
# Export Task Schemas
# =============================================================================


# Supported export formats
ExportFormatType = Literal["csv", "xlsx", "pdf"]


class ExportFormat(BaseModel):
    """Export format options."""

    format: ExportFormatType = Field(description="Export format: csv, xlsx, or pdf")


class ExportTaskCreate(BaseModel):
    """Request to create an export task."""

    project_id: int
    format: ExportFormatType = Field(description="Export format: csv, xlsx, or pdf")
    matrix_config_id: Optional[int] = Field(
        default=None, description="Use saved matrix config"
    )
    filters: Optional[RTMFilters] = Field(
        default=None, description="Filters to apply (overrides config)"
    )
    include_details: bool = Field(
        default=False, description="Include detailed link information"
    )


class ExportTaskStatus(BaseModel):
    """Status of an export task."""

    task_id: str
    status: str = Field(description="Status: pending, processing, completed, failed")
    progress_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    download_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
