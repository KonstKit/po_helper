from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.sprint import Sprint
    from app.models.sprint import WorkLog


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jira_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, nullable=False)
    priority: Mapped[str | None] = mapped_column(String)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    sprint_id: Mapped[int | None] = mapped_column(ForeignKey("sprints.id"), index=True)
    assignee_email: Mapped[str | None] = mapped_column(String)
    assignee_name: Mapped[str | None] = mapped_column(String)
    reporter_email: Mapped[str | None] = mapped_column(String)
    reporter_name: Mapped[str | None] = mapped_column(String)

    estimate_hours: Mapped[float | None] = mapped_column(Float)
    spent_hours: Mapped[float | None] = mapped_column(Float)
    remaining_hours: Mapped[float | None] = mapped_column(Float)

    is_blocker: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked_by: Mapped[list[str] | None] = mapped_column(JSON)
    blocks: Mapped[list[str] | None] = mapped_column(JSON)

    created_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    labels: Mapped[list[str] | None] = mapped_column(JSON)
    components: Mapped[list[str] | None] = mapped_column(JSON)
    custom_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Business value tracking (optional fields)
    business_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_delivered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    roi: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    project: Mapped[Project | None] = relationship("Project", back_populates="tasks")
    sprint: Mapped[Sprint | None] = relationship("Sprint", back_populates="tasks")
    worklogs: Mapped[list[WorkLog]] = relationship("WorkLog", back_populates="task")
