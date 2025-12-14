from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class JiraFieldMapping(Base):
    """Model for storing Jira field mappings discovered or configured by users"""

    __tablename__ = "jira_field_mappings"

    id = Column(Integer, primary_key=True, index=True)
    jira_instance_url = Column(String(255), index=True)
    project_key = Column(String(50), index=True)
    field_type = Column(String(50), nullable=False)  # 'sprint', 'epic_link', 'story_points', etc
    field_id = Column(String(50), nullable=False)  # 'customfield_10601' or 'auto'
    field_name = Column(String(255))
    discovery_method = Column(String(20))  # 'manual', 'auto', 'api'
    confidence_score = Column(Float)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
