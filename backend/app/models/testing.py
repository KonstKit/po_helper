from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class TestResult(Base):
    __tablename__ = "test_results"
    __test__ = False

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    suite: Mapped[str | None] = mapped_column(String, nullable=True)
    classname: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)  # passed|failed|skipped|error
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str | None] = mapped_column(String, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CoverageReport(Base):
    __tablename__ = "coverage_reports"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    line_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    function_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    report_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileCoverage(Base):
    __tablename__ = "file_coverage"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    coverage_report_id: Mapped[int | None] = mapped_column(Integer, index=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    file_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    line_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    lines_covered: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lines_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlakyTest(Base):
    """
    Tracks tests that exhibit flaky behavior (intermittent failures).
    A test is considered flaky if it passes and fails on the same commit.
    """

    __tablename__ = "flaky_tests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)

    # Test identification
    suite: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    classname: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    test_name: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # Flakiness metrics
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    flakiness_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Status tracking
    status: Mapped[str] = mapped_column(
        String, default="active"
    )  # active, fixed, ignored, quarantined
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Analysis
    failure_patterns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    suspected_cause: Mapped[str | None] = mapped_column(String, nullable=True)
    affected_commits: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Resolution
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)
    fix_pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CoverageHistory(Base):
    """
    Time-series coverage data for tracking trends over time.
    Aggregated daily/weekly for efficient querying.
    """

    __tablename__ = "coverage_history"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    sprint_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    # Time bucket
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    period_type: Mapped[str] = mapped_column(String, default="daily")  # daily, weekly, monthly

    # Coverage metrics
    line_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    function_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    statement_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Delta from previous period
    line_coverage_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Counts
    total_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covered_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_branches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covered_branches: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Test metrics
    total_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skipped_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flaky_tests: Mapped[int | None] = mapped_column(Integer, nullable=True)
    test_pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Source
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ComponentCoverage(Base):
    """
    Aggregated coverage by component/module (directory path).
    Helps identify under-tested areas of the codebase.
    """

    __tablename__ = "component_coverage"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int | None] = mapped_column(Integer, index=True)
    coverage_report_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    # Component identification
    component_path: Mapped[str] = mapped_column(String, nullable=False, index=True)
    component_name: Mapped[str | None] = mapped_column(String, nullable=True)

    # Coverage metrics
    line_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    branch_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    function_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Counts
    total_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covered_files: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)
    covered_lines: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Complexity metrics
    average_complexity: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_complexity: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Risk assessment
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)

    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
