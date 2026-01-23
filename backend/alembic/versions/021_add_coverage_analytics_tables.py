"""Add coverage analytics tables (flaky tests, coverage history, component coverage)

Revision ID: 021
Revises: 020
Create Date: 2024-12-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if table exists using SQLAlchemy inspector."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # Create flaky_tests table
    if not _table_exists("flaky_tests"):
        op.create_table(
            "flaky_tests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("suite", sa.String(), nullable=True),
            sa.Column("classname", sa.String(), nullable=True),
            sa.Column("test_name", sa.String(), nullable=False),
            sa.Column("total_runs", sa.Integer(), server_default="0"),
            sa.Column("failure_count", sa.Integer(), server_default="0"),
            sa.Column("flakiness_rate", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), server_default="active"),
            sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("first_detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("failure_patterns", sa.JSON(), nullable=True),
            sa.Column("suspected_cause", sa.String(), nullable=True),
            sa.Column("affected_commits", sa.JSON(), nullable=True),
            sa.Column("assigned_to", sa.String(), nullable=True),
            sa.Column("fix_pr_number", sa.Integer(), nullable=True),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_flaky_tests_id", "flaky_tests", ["id"])
        op.create_index("ix_flaky_tests_project_id", "flaky_tests", ["project_id"])
        op.create_index("ix_flaky_tests_suite", "flaky_tests", ["suite"])
        op.create_index("ix_flaky_tests_classname", "flaky_tests", ["classname"])
        op.create_index("ix_flaky_tests_test_name", "flaky_tests", ["test_name"])

    # Create coverage_history table
    if not _table_exists("coverage_history"):
        op.create_table(
            "coverage_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("sprint_id", sa.Integer(), nullable=True),
            sa.Column("date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_type", sa.String(), server_default="daily"),
            sa.Column("line_coverage", sa.Float(), nullable=True),
            sa.Column("branch_coverage", sa.Float(), nullable=True),
            sa.Column("function_coverage", sa.Float(), nullable=True),
            sa.Column("statement_coverage", sa.Float(), nullable=True),
            sa.Column("line_coverage_delta", sa.Float(), nullable=True),
            sa.Column("branch_coverage_delta", sa.Float(), nullable=True),
            sa.Column("total_lines", sa.Integer(), nullable=True),
            sa.Column("covered_lines", sa.Integer(), nullable=True),
            sa.Column("total_branches", sa.Integer(), nullable=True),
            sa.Column("covered_branches", sa.Integer(), nullable=True),
            sa.Column("total_tests", sa.Integer(), nullable=True),
            sa.Column("passed_tests", sa.Integer(), nullable=True),
            sa.Column("failed_tests", sa.Integer(), nullable=True),
            sa.Column("skipped_tests", sa.Integer(), nullable=True),
            sa.Column("flaky_tests", sa.Integer(), nullable=True),
            sa.Column("test_pass_rate", sa.Float(), nullable=True),
            sa.Column("commit_sha", sa.String(), nullable=True),
            sa.Column("pr_number", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_coverage_history_id", "coverage_history", ["id"])
        op.create_index("ix_coverage_history_project_id", "coverage_history", ["project_id"])
        op.create_index("ix_coverage_history_sprint_id", "coverage_history", ["sprint_id"])
        op.create_index("ix_coverage_history_date", "coverage_history", ["date"])

    # Create component_coverage table
    if not _table_exists("component_coverage"):
        op.create_table(
            "component_coverage",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("coverage_report_id", sa.Integer(), nullable=True),
            sa.Column("component_path", sa.String(), nullable=False),
            sa.Column("component_name", sa.String(), nullable=True),
            sa.Column("line_coverage", sa.Float(), nullable=True),
            sa.Column("branch_coverage", sa.Float(), nullable=True),
            sa.Column("function_coverage", sa.Float(), nullable=True),
            sa.Column("total_files", sa.Integer(), nullable=True),
            sa.Column("covered_files", sa.Integer(), nullable=True),
            sa.Column("total_lines", sa.Integer(), nullable=True),
            sa.Column("covered_lines", sa.Integer(), nullable=True),
            sa.Column("average_complexity", sa.Float(), nullable=True),
            sa.Column("max_complexity", sa.Float(), nullable=True),
            sa.Column("risk_score", sa.Float(), nullable=True),
            sa.Column("priority", sa.String(), nullable=True),
            sa.Column("commit_sha", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_component_coverage_id", "component_coverage", ["id"])
        op.create_index("ix_component_coverage_project_id", "component_coverage", ["project_id"])
        op.create_index("ix_component_coverage_coverage_report_id", "component_coverage", ["coverage_report_id"])
        op.create_index("ix_component_coverage_component_path", "component_coverage", ["component_path"])
        op.create_index("ix_component_coverage_commit_sha", "component_coverage", ["commit_sha"])


def downgrade() -> None:
    op.drop_table("component_coverage")
    op.drop_table("coverage_history")
    op.drop_table("flaky_tests")
