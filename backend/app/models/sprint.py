from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.task import Task


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jira_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    goal: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(
        String, index=True
    )  # future, active, closed - indexed for filtering
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True
    )  # Added index for performance

    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    complete_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    velocity: Mapped[float | None] = mapped_column(Float)
    commitment: Mapped[float | None] = mapped_column(Float)
    completed: Mapped[float | None] = mapped_column(Float)
    wip_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    project: Mapped[Project | None] = relationship("Project", back_populates="sprints")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="sprint")

    # Composite index for the common query pattern in analytics.project_sprints
    __table_args__ = (Index("ix_sprints_project_start_date", "project_id", "start_date"),)


class WorkLog(Base):
    __tablename__ = "worklogs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jira_id: Mapped[str | None] = mapped_column(String, unique=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    author_email: Mapped[str | None] = mapped_column(String)
    author_name: Mapped[str | None] = mapped_column(String)

    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(String)
    started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task: Mapped[Task | None] = relationship("Task", back_populates="worklogs")


class SprintSnapshot(Base):
    __tablename__ = "sprint_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), index=True)
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    total_estimate_hours: Mapped[float | None] = mapped_column(Float)
    remaining_hours: Mapped[float | None] = mapped_column(Float)
    completed_hours: Mapped[float | None] = mapped_column(Float)
    scope_added_hours: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sprint: Mapped["Sprint | None"] = relationship("Sprint", backref="snapshots")
