"""add indexes for pull request analytics"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_pull_requests_opened_at', 'pull_requests', ['opened_at'])
    op.create_index('ix_pull_requests_merged_at', 'pull_requests', ['merged_at'])
    op.create_index('ix_pull_requests_provider_state', 'pull_requests', ['provider', 'state'])


def downgrade():
    op.drop_index('ix_pull_requests_provider_state', table_name='pull_requests')
    op.drop_index('ix_pull_requests_merged_at', table_name='pull_requests')
    op.drop_index('ix_pull_requests_opened_at', table_name='pull_requests')
