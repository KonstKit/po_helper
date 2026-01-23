"""Add missing indexes for common filter and query patterns.

This migration adds indexes that were identified through query analysis:
- Task.status: frequently used in list filtering
- Task.assignee_name: team views and assignments
- TestResult.created_at: time-series queries
- SuggestedLink.status: pending link queue
- Composite indexes for common multi-column filters
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists using SQLAlchemy inspector."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    try:
        indexes = inspector.get_indexes(table_name)
        return any(idx['name'] == index_name for idx in indexes)
    except Exception:
        return False


# Single-column indexes for filter fields
_SINGLE_INDEXES = (
    # Tasks - high-frequency filters
    ("ix_tasks_status", "tasks", ["status"]),
    ("ix_tasks_assignee_name", "tasks", ["assignee_name"]),
    ("ix_tasks_task_type", "tasks", ["task_type"]),
    ("ix_tasks_priority", "tasks", ["priority"]),

    # TestResult - time-series queries
    ("ix_test_results_created_at", "test_results", ["created_at"]),
    ("ix_test_results_status", "test_results", ["status"]),

    # SuggestedLink - pending queue filtering
    ("ix_suggested_links_status", "suggested_links", ["status"]),

    # EscapedDefect - status filtering
    ("ix_escaped_defects_status", "escaped_defects", ["status"]),
    ("ix_escaped_defects_severity", "escaped_defects", ["severity"]),
)

# Composite indexes for common multi-column query patterns
_COMPOSITE_INDEXES = (
    # Tasks: project + status is very common filter combo
    ("ix_tasks_project_status", "tasks", ["project_id", "status"]),
    # Tasks: sprint + status for sprint boards
    ("ix_tasks_sprint_status", "tasks", ["sprint_id", "status"]),

    # Test results: time-filtered by commit
    ("ix_test_results_commit_created", "test_results", ["commit_sha", "created_at"]),

    # SuggestedLink: project + status for pending queue per project
    ("ix_suggested_links_project_status", "suggested_links", ["project_id", "status"]),

    # EscapedDefect: project + status for defect tracking
    ("ix_escaped_defects_project_status", "escaped_defects", ["project_id", "status"]),
)

_ALL_INDEXES = _SINGLE_INDEXES + _COMPOSITE_INDEXES


def upgrade() -> None:
    for name, table, columns in _ALL_INDEXES:
        # Skip if table doesn't exist
        if not _table_exists(table):
            continue
        # Skip if index already exists
        if _index_exists(table, name):
            continue

        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(_ALL_INDEXES):
        if _table_exists(table):
            op.drop_index(name, table_name=table, if_exists=True)
