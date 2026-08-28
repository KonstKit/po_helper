from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    JSON,
    Float,
    Boolean,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from app.core.database import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )

    type: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # requirement|jira_issue|commit|pr|pipeline|deployment|test_case|test_run|confluence_page|...
    source: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # jira|confluence|github|gitlab|testrail|ci|internal
    external_id: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # external key/id (e.g., JIRA-123, SHA)
    source_system: Mapped[str | None] = mapped_column(String, nullable=True)
    source_reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ingestion_run_id: Mapped[str | None] = mapped_column(String, nullable=True)

    display_key: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Versioning
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifacts.id"), index=True, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "type",
            "source",
            "external_id",
            "version",
            name="uq_artifact_identity",
        ),
        Index("ix_artifact_identity", "tenant_id", "project_id", "type", "source", "external_id"),
    )


class ArtifactLink(Base):
    __tablename__ = "artifact_links"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    created_via: Mapped[str | None] = mapped_column(String, nullable=True)  # manual|rule|sync
    source_system: Mapped[str | None] = mapped_column(String, nullable=True)
    source_reference_id: Mapped[str | None] = mapped_column(String, nullable=True)
    method: Mapped[str | None] = mapped_column(String, nullable=True)

    from_artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id"), nullable=False
    )
    to_artifact_id: Mapped[int] = mapped_column(Integer, ForeignKey("artifacts.id"), nullable=False)
    link_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # implements|tests|deploys|derives_from|relates_to|blocks
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    confidence_factors: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "from_artifact_id",
            "to_artifact_id",
            "link_type",
            name="uq_artifact_link",
        ),
        Index("ix_links_from_type", "from_artifact_id", "link_type", "to_artifact_id"),
        Index("ix_links_to_type", "to_artifact_id", "link_type", "from_artifact_id"),
        # Partial index for high-confidence links (SQLite supports WHERE indexes)
        Index("idx_links_confidence_high", "from_artifact_id", "to_artifact_id"),
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )

    type: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    auth: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    scopes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class SyncState(Base):
    __tablename__ = "sync_states"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"), index=True, nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )

    last_cursor: Mapped[str | None] = mapped_column(String, nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    etag: Mapped[str | None] = mapped_column(String, nullable=True)
    lag_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    rate_limit_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class LegacyMapping(Base):
    __tablename__ = "legacy_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    old_table: Mapped[str] = mapped_column(String, nullable=False)
    old_id: Mapped[int] = mapped_column(Integer, nullable=False)
    new_artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id"), index=True, nullable=False
    )
    migrated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_actor_id", "actor_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )


class SuggestedLink(Base):
    """Stores auto-generated link suggestions awaiting user approval."""

    __tablename__ = "suggested_links"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )

    from_artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id"), index=True, nullable=False
    )
    to_artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id"), index=True, nullable=False
    )
    suggested_link_type: Mapped[str] = mapped_column(String, nullable=False)

    # Similarity scoring
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1 cosine similarity
    method: Mapped[str] = mapped_column(String, nullable=False)  # tfidf|semantic|keyword|hybrid
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # Human-readable explanation

    # Review status
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "project_id",
            "from_artifact_id",
            "to_artifact_id",
            "suggested_link_type",
            name="uq_suggested_link",
        ),
        Index("ix_suggested_status", "status", "project_id"),
        Index("ix_suggested_score", "similarity_score"),
    )


class Baseline(Base):
    __tablename__ = "baselines"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BaselineItem(Base):
    __tablename__ = "baseline_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    baseline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("baselines.id"), nullable=False, index=True
    )
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artifacts.id"), nullable=True, index=True
    )
    link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artifact_links.id"), nullable=True, index=True
    )
    included_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Projection(Base):
    __tablename__ = "projections"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectionItem(Base):
    __tablename__ = "projection_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    projection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projections.id"), nullable=False, index=True
    )
    artifact_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artifacts.id"), nullable=True, index=True
    )
    link_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("artifact_links.id"), nullable=True, index=True
    )
    included_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class SyncTask(Base):
    __tablename__ = "sync_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id"), index=True, nullable=True
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("traceability_rules.id"), index=True, nullable=True
    )
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cursor_in: Mapped[str | None] = mapped_column(String, nullable=True)
    cursor_out: Mapped[str | None] = mapped_column(String, nullable=True)
    item_counts: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str | None] = mapped_column(String, nullable=True)  # manual|schedule|webhook
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_sync_tasks_status_heartbeat", "status", "heartbeat_at", "started_at"),
        Index(
            "uq_sync_tasks_project_task_running",
            "project_id",
            "task_type",
            unique=True,
            sqlite_where=text("status = 'running'"),
            postgresql_where=text("status = 'running'"),
        ),
    )


class ConnectorConfig(Base):
    __tablename__ = "connector_configs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    provider: Mapped[str] = mapped_column(String, nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    auth_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    rate_limit_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class MatrixConfig(Base):
    """Saved RTM matrix configurations (projections) for reusable matrix views."""

    __tablename__ = "matrix_configs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Saved filter configuration
    filters_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Pagination defaults
    pagination_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Display options (column order, grouping, etc.)
    display_options_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    __table_args__ = (Index("ix_matrix_config_project", "project_id", "is_default"),)


class ExportTask(Base):
    """Async export task tracking for RTM matrix exports."""

    __tablename__ = "export_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=True
    )

    export_type: Mapped[str] = mapped_column(String(20), nullable=False)  # matrix, coverage, etc.
    format: Mapped[str] = mapped_column(String(10), nullable=False)  # csv, xlsx, pdf
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    progress_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Config used for export
    config_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Result
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_export_task_status", "status", "created_at"),)
