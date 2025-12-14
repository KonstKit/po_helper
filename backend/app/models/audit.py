from sqlalchemy import Column, Integer, Float, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class BusinessValueAudit(Base):
    __tablename__ = "business_value_audit"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False)
    old_value = Column(Float, nullable=True)
    new_value = Column(Float, nullable=True)
    old_delivered = Column(Boolean, nullable=True)
    new_delivered = Column(Boolean, nullable=True)
    old_roi = Column(Float, nullable=True)
    new_roi = Column(Float, nullable=True)
    changed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

