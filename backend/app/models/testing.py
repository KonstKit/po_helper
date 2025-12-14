from __future__ import annotations

from sqlalchemy import Column, Integer, String, DateTime, Float, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class TestResult(Base):
    __tablename__ = "test_results"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=True)
    commit_sha = Column(String, index=True, nullable=True)
    pr_number = Column(Integer, index=True, nullable=True)
    suite = Column(String, nullable=True)
    classname = Column(String, nullable=True)
    name = Column(String, nullable=True)
    status = Column(String, nullable=True)  # passed|failed|skipped|error
    duration = Column(Float, nullable=True)
    message = Column(String, nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CoverageReport(Base):
    __tablename__ = "coverage_reports"

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=True)
    commit_sha = Column(String, index=True, nullable=True)
    pr_number = Column(Integer, index=True, nullable=True)
    line_coverage = Column(Float, nullable=True)
    branch_coverage = Column(Float, nullable=True)
    report_url = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FileCoverage(Base):
    __tablename__ = "file_coverage"

    id = Column(Integer, primary_key=True, index=True)
    coverage_report_id = Column(Integer, index=True)
    provider = Column(String, nullable=True)
    commit_sha = Column(String, index=True, nullable=True)
    file_path = Column(String, nullable=False, index=True)
    line_coverage = Column(Float, nullable=True)
    branch_coverage = Column(Float, nullable=True)
    lines_covered = Column(Integer, nullable=True)
    lines_total = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
