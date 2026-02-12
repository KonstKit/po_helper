"""add_audit_log_fields

Revision ID: 029_add_audit_log_fields
Revises: 028_add_matrix_configs_export_tasks
Create Date: 2026-02-05

Adds project_id, request_id, and outcome fields to audit_log.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "029_add_audit_log_fields"
down_revision = "028_add_matrix_configs_export_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_log",
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
    )
    op.add_column("audit_log", sa.Column("request_id", sa.String(), nullable=True))
    op.add_column("audit_log", sa.Column("outcome", sa.String(), nullable=True))

    op.create_index("ix_audit_log_project_id", "audit_log", ["project_id"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index("ix_audit_log_request_id", "audit_log", ["request_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_request_id", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_id", table_name="audit_log")
    op.drop_index("ix_audit_log_project_id", table_name="audit_log")

    op.drop_column("audit_log", "outcome")
    op.drop_column("audit_log", "request_id")
    op.drop_column("audit_log", "project_id")
