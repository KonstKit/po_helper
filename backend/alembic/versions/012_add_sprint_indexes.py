"""Add Sprint performance indexes

Revision ID: 012
Revises: 011
Create Date: 2025-09-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes to improve Sprint query performance."""

    # Add index on project_id for filtering
    op.create_index(
        'ix_sprints_project_id',
        'sprints',
        ['project_id'],
        if_not_exists=True
    )

    # Add index on state for filtering active/closed sprints
    op.create_index(
        'ix_sprints_state',
        'sprints',
        ['state'],
        if_not_exists=True
    )

    # Add index on start_date for sorting
    op.create_index(
        'ix_sprints_start_date',
        'sprints',
        ['start_date'],
        if_not_exists=True
    )

    # Add composite index for the common query pattern
    # WHERE project_id = ? ORDER BY start_date DESC
    op.create_index(
        'ix_sprints_project_start_date',
        'sprints',
        ['project_id', 'start_date'],
        if_not_exists=True
    )


def downgrade() -> None:
    """Remove Sprint performance indexes."""

    op.drop_index('ix_sprints_project_start_date', table_name='sprints')
    op.drop_index('ix_sprints_start_date', table_name='sprints')
    op.drop_index('ix_sprints_state', table_name='sprints')
    op.drop_index('ix_sprints_project_id', table_name='sprints')