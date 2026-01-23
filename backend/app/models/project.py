from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project_repository import ProjectRepository
    from app.models.sprint import Sprint
    from app.models.task import Task
    from app.models.traceability_rule import TraceabilityRule
    from app.models.user import User


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jira_key: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    budget: Mapped[float | None] = mapped_column(Float)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="active")
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    quality_thresholds: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    owner: Mapped[User | None] = relationship("User", backref="projects")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="project")
    sprints: Mapped[list[Sprint]] = relationship("Sprint", back_populates="project")
    project_repositories: Mapped[list[ProjectRepository]] = relationship(
        "ProjectRepository", back_populates="project", cascade="all, delete-orphan"
    )
    traceability_rules: Mapped[list[TraceabilityRule]] = relationship(
        "TraceabilityRule", back_populates="project"
    )
