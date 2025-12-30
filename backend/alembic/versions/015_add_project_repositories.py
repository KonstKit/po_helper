"""add project repositories relationship

Revision ID: 015_add_project_repositories
Revises: 014_create_integration_settings_table
Create Date: 2025-01-29 08:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '015_add_project_repositories'
down_revision = '014'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists (database-agnostic)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade():
    # Check if table already exists
    if _table_exists('project_repositories'):
        return  # Table already exists, skip creation

    # Create project_repositories association table
    op.create_table('project_repositories',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.Column('is_primary', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), onupdate=sa.func.now()),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('project_id', 'repository_id', name='uq_project_repository')
    )

    # Add indexes for faster queries
    op.create_index('ix_project_repositories_project_id', 'project_repositories', ['project_id'])
    op.create_index('ix_project_repositories_repository_id', 'project_repositories', ['repository_id'])
    op.create_index('ix_project_repositories_is_primary', 'project_repositories', ['is_primary'])


def downgrade():
    # Check if table exists before trying to drop it
    if not _table_exists('project_repositories'):
        return  # Table doesn't exist, nothing to drop

    op.drop_index('ix_project_repositories_is_primary', 'project_repositories', if_exists=True)
    op.drop_index('ix_project_repositories_repository_id', 'project_repositories', if_exists=True)
    op.drop_index('ix_project_repositories_project_id', 'project_repositories', if_exists=True)
    op.drop_table('project_repositories')