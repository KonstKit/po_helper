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
    UniqueConstraint,
    Index,
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

    type: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # requirement|jira_issue|commit|pr|pipeline|deployment|test_case|test_run|confluence_page|...
    source: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # jira|confluence|github|gitlab|testrail|ci|internal
    external_id: Mapped[str] = mapped_column(
        String, index=True, nullable=False
    )  # external key/id (e.g., JIRA-123, SHA)

    display_key: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Versioning
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)

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
        Integer, ForeignKey("artifacts.id"), nullable=False
    )
    migrated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SuggestedLink(Base):
    """Stores auto-generated link suggestions awaiting user approval."""

    __tablename__ = "suggested_links"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )

    from_artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id"), nullable=False
    )
    to_artifact_id: Mapped[int] = mapped_column(Integer, ForeignKey("artifacts.id"), nullable=False)
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
