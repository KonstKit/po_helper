"""Add quality metrics tables (escaped defects, defect metrics)

Revision ID: 020
Revises: 019
Create Date: 2024-12-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "020"
down_revision = "019_add_capacity_health_cfd_tables"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if table exists using SQLAlchemy inspector."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    # Create escaped_defects table
    if not _table_exists("escaped_defects"):
        op.create_table(
            "escaped_defects",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("sprint_id", sa.Integer(), nullable=True),
            sa.Column("external_id", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("severity", sa.String(), nullable=False, server_default="medium"),
            sa.Column("priority", sa.String(), nullable=True),
            sa.Column("environment", sa.String(), nullable=False, server_default="production"),
            sa.Column("root_cause", sa.String(), nullable=True),
            sa.Column("affected_component", sa.String(), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("time_to_detect_hours", sa.Float(), nullable=True),
            sa.Column("time_to_resolve_hours", sa.Float(), nullable=True),
            sa.Column("fix_commit_sha", sa.String(), nullable=True),
            sa.Column("fix_pr_number", sa.Integer(), nullable=True),
            sa.Column("customers_affected", sa.Integer(), nullable=True),
            sa.Column("revenue_impact", sa.Float(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="open"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["sprint_id"], ["sprints.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_escaped_defects_id", "escaped_defects", ["id"])
        op.create_index("ix_escaped_defects_project_id", "escaped_defects", ["project_id"])
        op.create_index("ix_escaped_defects_sprint_id", "escaped_defects", ["sprint_id"])
        op.create_index("ix_escaped_defects_external_id", "escaped_defects", ["external_id"])
        op.create_index("ix_escaped_defects_severity", "escaped_defects", ["severity"])
        op.create_index("ix_escaped_defects_status", "escaped_defects", ["status"])

    # Create defect_metrics table
    if not _table_exists("defect_metrics"):
        op.create_table(
            "defect_metrics",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("sprint_id", sa.Integer(), nullable=True),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("total_defects", sa.Integer(), server_default="0"),
            sa.Column("defects_found_in_dev", sa.Integer(), server_default="0"),
            sa.Column("defects_found_in_qa", sa.Integer(), server_default="0"),
            sa.Column("defects_found_in_prod", sa.Integer(), server_default="0"),
            sa.Column("critical_defects", sa.Integer(), server_default="0"),
            sa.Column("high_defects", sa.Integer(), server_default="0"),
            sa.Column("medium_defects", sa.Integer(), server_default="0"),
            sa.Column("low_defects", sa.Integer(), server_default="0"),
            sa.Column("defect_density", sa.Float(), nullable=True),
            sa.Column("defect_removal_efficiency", sa.Float(), nullable=True),
            sa.Column("escape_rate", sa.Float(), nullable=True),
            sa.Column("mean_time_to_resolve_hours", sa.Float(), nullable=True),
            sa.Column("mean_time_to_detect_hours", sa.Float(), nullable=True),
            sa.Column("lines_of_code", sa.Integer(), nullable=True),
            sa.Column("code_churn", sa.Integer(), nullable=True),
            sa.Column("test_automation_percent", sa.Float(), nullable=True),
            sa.Column("test_pass_rate", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["sprint_id"], ["sprints.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_defect_metrics_id", "defect_metrics", ["id"])
        op.create_index("ix_defect_metrics_project_id", "defect_metrics", ["project_id"])
        op.create_index("ix_defect_metrics_sprint_id", "defect_metrics", ["sprint_id"])
        op.create_index("ix_defect_metrics_period", "defect_metrics", ["period_start", "period_end"])


def downgrade() -> None:
    op.drop_table("defect_metrics")
    op.drop_table("escaped_defects")
