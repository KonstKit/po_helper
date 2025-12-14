from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, JSON, Boolean, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Sprint(Base):
    __tablename__ = "sprints"

    id = Column(Integer, primary_key=True, index=True)
    jira_id = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    goal = Column(String)
    state = Column(String, index=True)  # future, active, closed - indexed for filtering
    project_id = Column(Integer, ForeignKey("projects.id"), index=True)  # Added index for performance

    start_date = Column(DateTime(timezone=True), index=True)  # Added index for sorting
    end_date = Column(DateTime(timezone=True))
    complete_date = Column(DateTime(timezone=True))
    
    velocity = Column(Float)
    commitment = Column(Float)
    completed = Column(Float)
    wip_limit = Column(Integer, nullable=True)    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    project = relationship("Project", back_populates="sprints")
    tasks = relationship("Task", back_populates="sprint")

    # Composite index for the common query pattern in analytics.project_sprints
    __table_args__ = (
        Index('ix_sprints_project_start_date', 'project_id', 'start_date'),
    )


class WorkLog(Base):
    __tablename__ = "worklogs"
    
    id = Column(Integer, primary_key=True, index=True)
    jira_id = Column(String, unique=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True)
    author_email = Column(String)
    author_name = Column(String)
    
    time_spent_seconds = Column(Integer)
    comment = Column(String)
    started = Column(DateTime(timezone=True))
    created = Column(DateTime(timezone=True))
    updated = Column(DateTime(timezone=True))
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    task = relationship("Task", back_populates="worklogs")


class SprintSnapshot(Base):
    __tablename__ = "sprint_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    sprint_id = Column(Integer, ForeignKey("sprints.id"), index=True)
    date = Column(DateTime(timezone=True), index=True)
    total_estimate_hours = Column(Float)
    remaining_hours = Column(Float)
    completed_hours = Column(Float)
    scope_added_hours = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

