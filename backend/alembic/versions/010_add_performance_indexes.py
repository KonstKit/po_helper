"""add performance indexes for analytics"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


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
        try:
            op.create_index(name, table, columns)
        except Exception:
            # Index may already exist in some environments; continue gracefully.
            pass


def downgrade() -> None:
    for name, table, _ in reversed(_ALL_INDEXES):
        try:
            op.drop_index(name, table_name=table)
        except Exception:
            pass
