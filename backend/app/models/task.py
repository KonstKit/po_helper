from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float, JSON, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, index=True)
    jira_id = Column(String, unique=True, index=True, nullable=False)
    key = Column(String, index=True, nullable=False)
    summary = Column(String, nullable=False)
    description = Column(Text)
    task_type = Column(String)
    status = Column(String, nullable=False)
    priority = Column(String)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True)
    sprint_id = Column(Integer, ForeignKey("sprints.id"), index=True)
    assignee_email = Column(String)
    assignee_name = Column(String)
    reporter_email = Column(String)
    reporter_name = Column(String)
    
    estimate_hours = Column(Float)
    spent_hours = Column(Float)
    remaining_hours = Column(Float)
    
    is_blocker = Column(Boolean, default=False)
    blocked_by = Column(JSON)
    blocks = Column(JSON)
    
    created_date = Column(DateTime(timezone=True))
    updated_date = Column(DateTime(timezone=True))
    resolved_date = Column(DateTime(timezone=True))
    due_date = Column(DateTime(timezone=True))
    
    labels = Column(JSON)
    components = Column(JSON)
    custom_fields = Column(JSON)
    # Business value tracking (optional fields)
    business_value = Column(Float, nullable=True)
    value_delivered = Column(Boolean, nullable=True)
    roi = Column(Float, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    project = relationship("Project", back_populates="tasks")
    sprint = relationship("Sprint", back_populates="tasks")
    worklogs = relationship("WorkLog", back_populates="task")
