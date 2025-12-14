from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)  # github|gitlab
    repo_slug = Column(String, nullable=False, index=True)  # org/repo or group/project
    default_branch = Column(String, nullable=True)
    settings = Column(JSON, nullable=True)  # tokens/installation ids (stored encrypted elsewhere ideally)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    project_repositories = relationship("ProjectRepository", back_populates="repository", cascade="all, delete-orphan")


class Commit(Base):
    __tablename__ = "commits"

    id = Column(Integer, primary_key=True, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), index=True)
    sha = Column(String, nullable=False, index=True)
    message = Column(String, nullable=True)
    author_email = Column(String, nullable=True)
    author_name = Column(String, nullable=True)
    jira_keys = Column(JSON, nullable=True)  # list of keys
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)  # github|gitlab
    repository_id = Column(Integer, ForeignKey("repositories.id"), index=True)
    number = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=True)
    state = Column(String, nullable=True)  # open|closed|merged
    author_login = Column(String, nullable=True)
    head_sha = Column(String, nullable=True)
    review_count = Column(Integer, nullable=True)
    approvals_count = Column(Integer, nullable=True)
    opened_at = Column(DateTime(timezone=True), nullable=True)
    merged_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    jira_keys = Column(JSON, nullable=True)
    first_review_at = Column(DateTime(timezone=True), nullable=True)
    cycle_time_hours = Column(Float, nullable=True)
    lead_time_hours = Column(Float, nullable=True)
    time_to_first_review_hours = Column(Float, nullable=True)
    rework_count = Column(Integer, nullable=True)
    files_changed = Column(Integer, nullable=True)
    lines_added = Column(Integer, nullable=True)
    lines_deleted = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
