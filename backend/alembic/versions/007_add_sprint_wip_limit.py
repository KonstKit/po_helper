"""add sprint wip limit column

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa
from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return column_name in {col['name'] for col in inspector.get_columns(table_name)}


def upgrade():
    if not _column_exists('sprints', 'wip_limit'):
        with op.batch_alter_table('sprints') as batch_op:
            batch_op.add_column(sa.Column('wip_limit', sa.Integer(), nullable=True))


def downgrade():
    if _column_exists('sprints', 'wip_limit'):
        with op.batch_alter_table('sprints') as batch_op:
            batch_op.drop_column('wip_limit')
