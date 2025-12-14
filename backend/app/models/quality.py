from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, JSON, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base


class QualityGateHistory(Base):
    __tablename__ = "quality_gate_history"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    provider = Column(String, nullable=True)
    pr_number = Column(Integer, nullable=True, index=True)
    commit_sha = Column(String, nullable=True, index=True)
    passed = Column(Boolean, nullable=True)
    line_coverage = Column(Float, nullable=True)
    branch_coverage = Column(Float, nullable=True)
    reasons = Column(JSON, nullable=True)
    result_payload = Column(JSON, nullable=True)  # store raw response incl. check run link
    created_at = Column(DateTime(timezone=True), server_default=func.now())

