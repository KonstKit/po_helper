from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project_repository import ProjectRepository


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # github|gitlab
    repo_slug: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # org/repo or group/project
    default_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    settings: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )  # tokens/installation ids (stored encrypted elsewhere ideally)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # Relationships
    project_repositories: Mapped[list[ProjectRepository]] = relationship(
        "ProjectRepository", back_populates="repository", cascade="all, delete-orphan"
    )


class Commit(Base):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    sha: Mapped[str] = mapped_column(String, nullable=False, index=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    author_email: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    jira_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)  # list of keys
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # github|gitlab
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id"), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)  # open|closed|merged
    merged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    author_login: Mapped[str | None] = mapped_column(String, nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approvals_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_keys: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    first_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cycle_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_time_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_to_first_review_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    rework_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    files_changed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lines_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lines_deleted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
