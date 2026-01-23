"""add_mfa_fields

Revision ID: 026
Revises: 025
Create Date: 2025-10-07

Adds Multi-Factor Authentication (MFA) fields to users table:
- mfa_enabled: Whether MFA is enabled for the user
- mfa_secret: TOTP secret for generating codes
- mfa_backup_codes: JSON array of remaining backup codes
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '026_add_mfa_fields'
down_revision = '025_add_oauth_fields'
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """Check if a table exists (database-agnostic)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade():
    if not _table_exists('users'):
        return

    # Add MFA enabled flag
    if not _column_exists('users', 'mfa_enabled'):
        op.add_column(
            'users',
            sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='false')
        )

    # Add TOTP secret
    if not _column_exists('users', 'mfa_secret'):
        op.add_column(
            'users',
            sa.Column('mfa_secret', sa.String(length=64), nullable=True)
        )

    # Add backup codes (JSON array)
    if not _column_exists('users', 'mfa_backup_codes'):
        op.add_column(
            'users',
            sa.Column('mfa_backup_codes', sa.JSON(), nullable=True)
        )


def downgrade():
    if not _table_exists('users'):
        return

    # Drop MFA columns
    if _column_exists('users', 'mfa_backup_codes'):
        op.drop_column('users', 'mfa_backup_codes')

    if _column_exists('users', 'mfa_secret'):
        op.drop_column('users', 'mfa_secret')

    if _column_exists('users', 'mfa_enabled'):
        op.drop_column('users', 'mfa_enabled')
