"""add business value audit table

Revision ID: 008
Revises: 007
"""

import sqlalchemy as sa
from alembic import op


revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _ensure_index(table_name: str, name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx['name'] for idx in inspector.get_indexes(table_name)}
    if name in existing:
        return
    op.create_index(name, table_name, columns)


def _drop_index_if_exists(table_name: str, name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {idx['name'] for idx in inspector.get_indexes(table_name)}
    if name in existing:
        op.drop_index(name, table_name=table_name)


def upgrade():
    if not _table_exists('business_value_audit'):
        op.create_table(
            'business_value_audit',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('task_id', sa.Integer(), nullable=False),
            sa.Column('old_value', sa.Float(), nullable=True),
            sa.Column('new_value', sa.Float(), nullable=True),
            sa.Column('old_delivered', sa.Boolean(), nullable=True),
            sa.Column('new_delivered', sa.Boolean(), nullable=True),
            sa.Column('old_roi', sa.Float(), nullable=True),
            sa.Column('new_roi', sa.Float(), nullable=True),
            sa.Column('changed_by', sa.Integer(), nullable=True),
            sa.Column('reason', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name='fk_business_value_audit_task'),
        )
    if _table_exists('business_value_audit'):
        _ensure_index('business_value_audit', 'ix_business_value_audit_task_id', ['task_id'])


def downgrade():
    if _table_exists('business_value_audit'):
        _drop_index_if_exists('business_value_audit', 'ix_business_value_audit_task_id')
        op.drop_table('business_value_audit')
