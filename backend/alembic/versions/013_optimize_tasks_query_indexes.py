"""optimize tasks query performance with comprehensive indexes

Revision ID: 013
Revises: 012
Create Date: 2025-01-26
"""
from alembic import op
import sqlalchemy as sa


revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add comprehensive indexes for optimizing tasks query performance, especially for large limits."""

    # Composite indexes for common filter combinations
    # These will significantly speed up queries with multiple filters

    # 1. Most common: project_id + status (covering index includes common fields)
    try:
        op.create_index(
            'idx_tasks_project_status_covering',
            'tasks',
            ['project_id', 'status', 'id', 'key', 'summary', 'assignee_name', 'priority']
        )
    except Exception:
        pass

    # 2. Sprint-based queries
    try:
        op.create_index(
            'idx_tasks_sprint_status_covering',
            'tasks',
            ['sprint_id', 'status', 'id', 'key', 'summary']
        )
    except Exception:
        pass

    # 3. Assignee-based queries
    try:
        op.create_index(
            'idx_tasks_assignee_status',
            'tasks',
            ['assignee_email', 'status']
        )
    except Exception:
        pass

    # 4. Combined filter: project + sprint + status (common in dashboard)
    try:
        op.create_index(
            'idx_tasks_project_sprint_status',
            'tasks',
            ['project_id', 'sprint_id', 'status']
        )
    except Exception:
        pass

    # 5. Add index for ORDER BY created_at DESC (common default ordering)
    try:
        op.create_index(
            'idx_tasks_created_at_desc',
            'tasks',
            [sa.text('created_at DESC')]
        )
    except Exception:
        pass

    # 6. Partial index for active tasks (not completed/closed)
    try:
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tasks_active_partial
            ON tasks (project_id, sprint_id, assignee_email)
            WHERE status NOT IN ('Done', 'Closed', 'Resolved', 'Completed')
        """)
    except Exception:
        pass

    # 7. Index for pagination (LIMIT/OFFSET optimization)
    try:
        op.create_index(
            'idx_tasks_id_project',
            'tasks',
            ['id', 'project_id']
        )
    except Exception:
        pass


def downgrade() -> None:
    """Remove the optimization indexes."""

    indexes_to_drop = [
        'idx_tasks_project_status_covering',
        'idx_tasks_sprint_status_covering',
        'idx_tasks_assignee_status',
        'idx_tasks_project_sprint_status',
        'idx_tasks_created_at_desc',
        'idx_tasks_active_partial',
        'idx_tasks_id_project'
    ]

    for idx_name in indexes_to_drop:
        try:
            op.drop_index(idx_name, table_name='tasks')
        except Exception:
            pass