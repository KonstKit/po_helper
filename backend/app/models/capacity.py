"""
Capacity settings model for personalized team capacity tracking.
Supports per-assignee capacity overrides, focus factors, and time-bound settings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.sprint import Sprint


class CapacitySettings(Base):
    """
    Personal capacity settings for team members.

    Allows overriding the default capacity (hours_per_week) and focus_factor
    for individual team members. Settings can be time-bounded with valid_from/valid_to.

    Focus Factor represents the percentage of theoretical capacity that's actually
    productive (typically 70-85% due to meetings, interruptions, context switching).
    """

    __tablename__ = "capacity_settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    assignee_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    assignee_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Capacity configuration
    hours_per_week: Mapped[float] = mapped_column(Float, default=40.0, nullable=False)
    focus_factor: Mapped[float] = mapped_column(Float, default=0.8, nullable=False)

    # Time-bounded settings (optional)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Metadata
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    project: Mapped[Project | None] = relationship("Project", backref="capacity_settings")

    @property
    def effective_capacity(self) -> float:
        """Calculate effective weekly capacity = hours_per_week * focus_factor"""
        return (self.hours_per_week or 40.0) * (self.focus_factor or 0.8)

    def __repr__(self):
        return f"<CapacitySettings {self.assignee_email}: {self.hours_per_week}h/week @ {self.focus_factor}>"


class TeamHealthCheck(Base):
    """
    Team health check records for tracking team satisfaction and wellbeing.

    Metrics include:
    - satisfaction: Overall team satisfaction (1-5 scale)
    - workload_balance: How balanced the workload feels (1-5 scale)
    - technical_debt_pressure: How much tech debt is affecting work (1-5 scale)
    - collaboration_quality: Quality of team collaboration (1-5 scale)
    - happiness_index: Weighted average of all metrics
    """

    __tablename__ = "team_health_checks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprints.id"), nullable=True, index=True
    )

    # Health metrics (1-5 scale)
    satisfaction: Mapped[float | None] = mapped_column(Float, nullable=True)
    workload_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    technical_debt_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    collaboration_quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Computed index (weighted average)
    happiness_index: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Burnout risk indicators
    burnout_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    burnout_risk_factors: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Context
    check_date: Mapped[date] = mapped_column(Date, nullable=False)
    respondent_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped[Project] = relationship("Project", backref="health_checks")
    sprint: Mapped["Sprint | None"] = relationship("Sprint", backref="health_checks")

    def __repr__(self):
        return f"<TeamHealthCheck project={self.project_id} date={self.check_date} happiness={self.happiness_index}>"


class CFDSnapshot(Base):
    """
    Daily snapshot of task distribution by status for Cumulative Flow Diagram.

    Captures the state of tasks across all statuses at a point in time,
    enabling lead time analysis and bottleneck detection.
    """

    __tablename__ = "cfd_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    sprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("sprints.id"), nullable=True, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Status counts (common Jira statuses)
    backlog_count: Mapped[int] = mapped_column(Integer, default=0)
    todo_count: Mapped[int] = mapped_column(Integer, default=0)
    in_progress_count: Mapped[int] = mapped_column(Integer, default=0)
    in_review_count: Mapped[int] = mapped_column(Integer, default=0)
    testing_count: Mapped[int] = mapped_column(Integer, default=0)
    done_count: Mapped[int] = mapped_column(Integer, default=0)

    # Aggregated metrics
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    wip_count: Mapped[int] = mapped_column(Integer, default=0)

    # Flow metrics (calculated)
    throughput: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_cycle_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    project: Mapped[Project] = relationship("Project", backref="cfd_snapshots")
    sprint: Mapped[Sprint | None] = relationship("Sprint", backref="cfd_snapshots")

    def __repr__(self):
        return f"<CFDSnapshot project={self.project_id} date={self.snapshot_date} total={self.total_count}>"
