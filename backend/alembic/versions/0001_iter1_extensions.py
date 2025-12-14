"""iter1 extensions: PR metrics, business value fields

Revision ID: 0001
Revises: 
Create Date: 2025-09-07

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def _ensure_columns(table_name: str, columns: list[sa.Column]) -> None:
    """Add columns only when missing to support pre-populated dev DBs."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col['name'] for col in inspector.get_columns(table_name)}
    to_add = [column for column in columns if column.name not in existing]
    if not to_add:
        return
    with op.batch_alter_table(table_name, schema=None) as batch_op:
        for column in to_add:
            batch_op.add_column(column)


def upgrade() -> None:
    # Pull requests: add time_to_first_review_hours, rework_count
    _ensure_columns(
        'pull_requests',
        [
            sa.Column('time_to_first_review_hours', sa.Float(), nullable=True),
            sa.Column('rework_count', sa.Integer(), nullable=True),
        ],
    )

    # Tasks: add business value fields
    _ensure_columns(
        'tasks',
        [
            sa.Column('business_value', sa.Float(), nullable=True),
            sa.Column('value_delivered', sa.Boolean(), nullable=True),
            sa.Column('roi', sa.Float(), nullable=True),
        ],
    )


def downgrade() -> None:
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('roi')
        batch_op.drop_column('value_delivered')
        batch_op.drop_column('business_value')

    with op.batch_alter_table('pull_requests', schema=None) as batch_op:
        batch_op.drop_column('rework_count')
        batch_op.drop_column('time_to_first_review_hours')
