"""add_matrix_configs_export_tasks

Revision ID: 028_add_matrix_configs_export_tasks
Revises: 027_add_traceability_baselines_projections_sync
Create Date: 2026-01-23

Adds tables for:
- matrix_configs: Saved RTM matrix configurations (projections)
- export_tasks: Async export task tracking
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "028_add_matrix_configs_export_tasks"
down_revision = "027_add_traceability_baselines_projections_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create matrix_configs table
    op.create_table(
        "matrix_configs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("pagination_json", sa.JSON(), nullable=True),
        sa.Column("display_options_json", sa.JSON(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_matrix_configs_project_id", "matrix_configs", ["project_id"])
    op.create_index("ix_matrix_configs_created_by_id", "matrix_configs", ["created_by_id"])
    op.create_index(
        "ix_matrix_config_project_default", "matrix_configs", ["project_id", "is_default"]
    )

    # Create export_tasks table
    op.create_table(
        "export_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(64), unique=True, nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("export_type", sa.String(20), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("progress_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("config_json", sa.JSON(), nullable=True),
        sa.Column("file_path", sa.String(512), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_export_tasks_task_id", "export_tasks", ["task_id"], unique=True)
    op.create_index("ix_export_tasks_project_id", "export_tasks", ["project_id"])
    op.create_index("ix_export_tasks_created_by_id", "export_tasks", ["created_by_id"])
    op.create_index("ix_export_task_status", "export_tasks", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_task_status", table_name="export_tasks")
    op.drop_index("ix_export_tasks_created_by_id", table_name="export_tasks")
    op.drop_index("ix_export_tasks_project_id", table_name="export_tasks")
    op.drop_index("ix_export_tasks_task_id", table_name="export_tasks")
    op.drop_table("export_tasks")

    op.drop_index("ix_matrix_config_project_default", table_name="matrix_configs")
    op.drop_index("ix_matrix_configs_created_by_id", table_name="matrix_configs")
    op.drop_index("ix_matrix_configs_project_id", table_name="matrix_configs")
    op.drop_table("matrix_configs")
