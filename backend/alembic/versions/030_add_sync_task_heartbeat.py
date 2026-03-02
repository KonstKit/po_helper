"""add_sync_task_heartbeat

Revision ID: 030_add_sync_task_heartbeat
Revises: 029_add_audit_log_fields
Create Date: 2026-03-02

Adds heartbeat tracking for sync_tasks stale-running recovery.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "030_add_sync_task_heartbeat"
down_revision = "029_add_audit_log_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_tasks", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_sync_tasks_status_heartbeat",
        "sync_tasks",
        ["status", "heartbeat_at", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sync_tasks_status_heartbeat", table_name="sync_tasks")
    op.drop_column("sync_tasks", "heartbeat_at")
