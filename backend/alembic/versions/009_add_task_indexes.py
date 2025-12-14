"""add helpful task indexes for analytics

Revision ID: 009
Revises: 008
"""
from alembic import op
import sqlalchemy as sa


revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade():
    try:
        op.create_index('idx_task_sprint_status', 'tasks', ['sprint_id', 'status'])
    except Exception:
        pass
    try:
        op.create_index('idx_task_project_delivered', 'tasks', ['project_id', 'value_delivered'])
    except Exception:
        pass


def downgrade():
    try:
        op.drop_index('idx_task_project_delivered', table_name='tasks')
    except Exception:
        pass
    try:
        op.drop_index('idx_task_sprint_status', table_name='tasks')
    except Exception:
        pass

