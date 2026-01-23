from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class QualityGateHistory(Base):
    __tablename__ = "quality_gate_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    line_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EscapedDefect(Base):
    """
    Tracks defects that escaped QA and were found in production.
    Key metric for measuring test effectiveness.
    """

    __tablename__ = "escaped_defects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprints.id"), nullable=True, index=True
    )

    # Defect identification
    external_id: Mapped[str | None] = mapped_column(
        String, nullable=True, index=True
    )  # Jira ID, GitHub issue, etc.
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Severity classification
    severity: Mapped[str] = mapped_column(String, nullable=False, default="medium")
    priority: Mapped[str | None] = mapped_column(String, nullable=True)  # P0, P1, P2, P3

    # Environment where found
    environment: Mapped[str] = mapped_column(String, nullable=False, default="production")

    # Root cause analysis
    root_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    affected_component: Mapped[str | None] = mapped_column(String, nullable=True)

    # Timing metrics
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Time to detect (from release to detection) in hours
    time_to_detect_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Time to resolve (from detection to fix) in hours
    time_to_resolve_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Link to fix
    fix_commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    fix_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Customer impact
    customers_affected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revenue_impact: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # Estimated revenue impact

    # Status tracking
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="open"
    )  # open, investigating, resolved, closed

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )


class DefectMetrics(Base):
    """
    Aggregated defect metrics per sprint/project for tracking quality trends.
    Calculated periodically from EscapedDefect and other sources.
    """

    __tablename__ = "defect_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprints.id"), nullable=True, index=True
    )

    # Time period
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Core defect counts
    total_defects: Mapped[int] = mapped_column(Integer, default=0)  # All defects in period
    defects_found_in_dev: Mapped[int] = mapped_column(
        Integer, default=0
    )  # Found during development
    defects_found_in_qa: Mapped[int] = mapped_column(Integer, default=0)  # Found during QA/testing
    defects_found_in_prod: Mapped[int] = mapped_column(Integer, default=0)  # Escaped to production

    # By severity
    critical_defects: Mapped[int] = mapped_column(Integer, default=0)
    high_defects: Mapped[int] = mapped_column(Integer, default=0)
    medium_defects: Mapped[int] = mapped_column(Integer, default=0)
    low_defects: Mapped[int] = mapped_column(Integer, default=0)

    # Calculated metrics
    defect_density: Mapped[float | None] = mapped_column(Float, nullable=True)
    defect_removal_efficiency: Mapped[float | None] = mapped_column(Float, nullable=True)
    escape_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Resolution metrics
    mean_time_to_resolve_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_time_to_detect_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Code metrics (from coverage/analysis)
    lines_of_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # LOC for density calculation
    code_churn: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # Lines changed in period

    # Test metrics
    test_automation_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    test_pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
