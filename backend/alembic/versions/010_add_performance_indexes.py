"""add performance indexes for analytics"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _table_exists(table_name: str) -> bool:
    """Check if a table exists."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


_TASK_INDEXES = (
    ('ix_tasks_project_id', 'tasks', ['project_id']),
    ('ix_tasks_assignee_name', 'tasks', ['assignee_name']),
    ('ix_tasks_status', 'tasks', ['status']),
    ('ix_tasks_sprint_id', 'tasks', ['sprint_id']),
)

_SPRINT_INDEXES = (
    ('ix_sprints_project_id', 'sprints', ['project_id']),
    ('ix_sprints_start_date', 'sprints', ['start_date']),
)

_PULL_REQUEST_INDEXES = (
    ('ix_pull_requests_project_id', 'pull_requests', ['project_id']),
    ('ix_pull_requests_state', 'pull_requests', ['state']),
)

_ALL_INDEXES = _TASK_INDEXES + _SPRINT_INDEXES + _PULL_REQUEST_INDEXES


def upgrade() -> None:
    for name, table, columns in _ALL_INDEXES:
        # Skip if table doesn't exist
        if not _table_exists(table):
            continue
        # Skip if any column doesn't exist
        if not all(_column_exists(table, col) for col in columns):
            continue
        op.create_index(name, table, columns, if_not_exists=True)


def downgrade() -> None:
    for name, table, _ in reversed(_ALL_INDEXES):
        if _table_exists(table):
            op.drop_index(name, table_name=table, if_exists=True)
