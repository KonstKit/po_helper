"""create integration_settings table for storing external integration credentials

Revision ID: 014
Revises: 013
Create Date: 2025-09-26
"""
from alembic import op
import sqlalchemy as sa


revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ensure integration_settings table exists for Jira/Confluence credentials."""

    if not _table_exists('integration_settings'):
        op.create_table(
            'integration_settings',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('kind', sa.String(length=50), nullable=False, index=True),
            sa.Column('base_url', sa.String(length=512), nullable=True),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('api_token', sa.String(length=2048), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index('ix_integration_settings_kind', 'integration_settings', ['kind'], unique=True)
    else:
        # Ensure index exists even if table was pre-created via metadata.create_all
        _ensure_index('integration_settings', 'ix_integration_settings_kind', ['kind'], unique=True)


def downgrade() -> None:
    if _table_exists('integration_settings'):
        op.drop_index('ix_integration_settings_kind', table_name='integration_settings')
        op.drop_table('integration_settings')


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return insp.has_table(table_name)


def _ensure_index(table_name: str, index_name: str, columns: list[str], unique: bool = False) -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    existing = {idx['name'] for idx in insp.get_indexes(table_name)}
    if index_name not in existing:
        op.create_index(index_name, table_name, columns, unique=unique)
