"""add_running_sync_task_unique_lease

Revision ID: 031_add_running_sync_task_unique_lease
Revises: 030_add_sync_task_heartbeat
Create Date: 2026-03-06

Adds a unique partial index to enforce a single running sync lease
per project/task_type at the database level.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "031_add_running_sync_task_unique_lease"
down_revision = "030_add_sync_task_heartbeat"
branch_labels = None
depends_on = None


INDEX_NAME = "uq_sync_tasks_project_task_running"


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY project_id, task_type
                    ORDER BY COALESCE(heartbeat_at, started_at, created_at) DESC, id DESC
                ) AS rn
            FROM sync_tasks
            WHERE status = 'running' AND project_id IS NOT NULL
        )
        UPDATE sync_tasks
        SET
            status = 'failed',
            finished_at = COALESCE(finished_at, CURRENT_TIMESTAMP),
            heartbeat_at = COALESCE(heartbeat_at, CURRENT_TIMESTAMP),
            error_code = COALESCE(error_code, 'overlap_lease_migration'),
            error_message = COALESCE(
                error_message,
                'Auto-failed duplicate running sync task during lease migration'
            )
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
        "ON sync_tasks (project_id, task_type) "
        "WHERE status = 'running'"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
