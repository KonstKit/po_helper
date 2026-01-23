from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class JiraFieldMapping(Base):
    """Model for storing Jira field mappings discovered or configured by users"""

    __tablename__ = "jira_field_mappings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    jira_instance_url: Mapped[str | None] = mapped_column(String(255), index=True)
    project_key: Mapped[str | None] = mapped_column(String(50), index=True)
    field_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'sprint', 'epic_link', 'story_points', etc
    field_id: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # 'customfield_10601' or 'auto'
    field_name: Mapped[str | None] = mapped_column(String(255))
    discovery_method: Mapped[str | None] = mapped_column(String(20))  # 'manual', 'auto', 'api'
    confidence_score: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )
