"""add indexes for common foreign keys"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "016"
down_revision = "015_add_project_repositories"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_tasks_project_id", "tasks", ["project_id"]),
    ("ix_tasks_sprint_id", "tasks", ["sprint_id"]),
    ("ix_worklogs_task_id", "worklogs", ["task_id"]),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table, columns in INDEXES:
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name in existing:
            continue
        op.create_index(name, table, columns)


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
