from __future__ import annotations

from sqlalchemy import (
    Column,
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
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)

    type = Column(String, index=True, nullable=False)  # requirement|jira_issue|commit|pr|pipeline|deployment|test_case|test_run|confluence_page|...
    source = Column(String, index=True, nullable=False)  # jira|confluence|github|gitlab|testrail|ci|internal
    external_id = Column(String, index=True, nullable=False)  # external key/id (e.g., JIRA-123, SHA)

    display_key = Column(String, nullable=True)
    title = Column(String, nullable=True)
    status = Column(String, nullable=True)
    url = Column(String, nullable=True)
    meta = Column(JSON, nullable=True)

    # Versioning
    version = Column(Integer, nullable=False, default=1)
    parent_version_id = Column(Integer, ForeignKey("artifacts.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "type", "source", "external_id", "version", name="uq_artifact_identity"),
        Index("ix_artifact_identity", "tenant_id", "project_id", "type", "source", "external_id"),
    )


class ArtifactLink(Base):
    __tablename__ = "artifact_links"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)

    from_artifact_id = Column(Integer, ForeignKey("artifacts.id"), nullable=False)
    to_artifact_id = Column(Integer, ForeignKey("artifacts.id"), nullable=False)
    link_type = Column(String, nullable=False)  # implements|tests|deploys|derives_from|relates_to|blocks
    confidence = Column(Float, nullable=True)  # 0..1
    confidence_factors = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "project_id", "from_artifact_id", "to_artifact_id", "link_type", name="uq_artifact_link"),
        Index("ix_links_from_type", "from_artifact_id", "link_type", "to_artifact_id"),
        Index("ix_links_to_type", "to_artifact_id", "link_type", "from_artifact_id"),
        # Partial index for high-confidence links (SQLite supports WHERE indexes)
        Index("idx_links_confidence_high", "from_artifact_id", "to_artifact_id"),
    )


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)

    type = Column(String, nullable=False)  # jira|confluence|github|gitlab|testrail|ci
    base_url = Column(String, nullable=True)
    auth = Column(JSON, nullable=True)
    scopes = Column(JSON, nullable=True)
    settings = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SyncState(Base):
    __tablename__ = "sync_states"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=True)
    source_id = Column(Integer, ForeignKey("sources.id"), index=True, nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)

    last_cursor = Column(String, nullable=True)
    last_event_id = Column(String, nullable=True)
    etag = Column(String, nullable=True)
    lag_seconds = Column(Float, nullable=True)
    rate_limit_reset_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LegacyMapping(Base):
    __tablename__ = "legacy_mappings"

    id = Column(Integer, primary_key=True)
    old_table = Column(String, nullable=False)
    old_id = Column(Integer, nullable=False)
    new_artifact_id = Column(Integer, ForeignKey("artifacts.id"), nullable=False)
    migrated_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, index=True, nullable=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_id = Column(Integer, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
