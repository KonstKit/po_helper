from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class TraceabilityRule(Base):
    """
    Traceability rule configuration stored as React Flow JSON.
    """

    __tablename__ = "traceability_rules"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # React Flow data
    flow_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Metadata
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="custom")  # basic, advanced, custom
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)  # ["git", "jira", "bidirectional"]

    # Execution stats
    total_executions: Mapped[int] = mapped_column(Integer, default=0)
    successful_executions: Mapped[int] = mapped_column(Integer, default=0)
    failed_executions: Mapped[int] = mapped_column(Integer, default=0)
    last_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Scheduling / Automation
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger_on_webhook: Mapped[bool] = mapped_column(Boolean, default=False)
    execute_on_sync_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    webhook_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_scheduled_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Ownership
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    created_by: Mapped[User | None] = relationship("User", back_populates="traceability_rules")
    project: Mapped[Project | None] = relationship("Project", back_populates="traceability_rules")
    executions: Mapped[list["TraceabilityRuleExecution"]] = relationship(
        "TraceabilityRuleExecution", back_populates="rule", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<TraceabilityRule(id={self.id}, name='{self.name}', enabled={self.enabled})>"


class TraceabilityRuleExecution(Base):
    """
    Log of rule execution attempts.
    """

    __tablename__ = "traceability_rule_executions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    rule_id: Mapped[int] = mapped_column(
        ForeignKey("traceability_rules.id"), nullable=False, index=True
    )

    # Execution metadata
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # What triggered this run: manual | webhook | scheduled | post_sync.
    # Nullable for rows created before the column existed (plan_76).
    trigger_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Results
    links_created: Mapped[int] = mapped_column(Integer, default=0)
    links_updated: Mapped[int] = mapped_column(Integer, default=0)
    artifacts_processed: Mapped[int] = mapped_column(Integer, default=0)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Execution context
    execution_context: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationship
    rule: Mapped["TraceabilityRule"] = relationship("TraceabilityRule", back_populates="executions")

    def __repr__(self):
        return f"<TraceabilityRuleExecution(id={self.id}, rule_id={self.rule_id}, status='{self.status}')>"
