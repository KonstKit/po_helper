"""add_oauth_fields

Revision ID: 025
Revises: 024
Create Date: 2025-10-06

Adds OAuth2 SSO fields to users table:
- oauth_provider: The OAuth provider name (google, microsoft)
- oauth_id: The unique ID from the OAuth provider
- oauth_email: Email from OAuth (may differ from primary email)
- avatar_url: Profile picture URL from OAuth provider
- Nullable password for OAuth-only users

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '025_add_oauth_fields'
down_revision = '024_add_rule_scheduling_columns'
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


def _index_exists(table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {idx['name'] for idx in inspector.get_indexes(table_name)}
    return index_name in existing_indexes


def upgrade():
    if not _table_exists('users'):
        return

    # Add OAuth provider column
    if not _column_exists('users', 'oauth_provider'):
        op.add_column(
            'users',
            sa.Column('oauth_provider', sa.String(length=50), nullable=True)
        )

    # Add OAuth ID column (unique per provider)
    if not _column_exists('users', 'oauth_id'):
        op.add_column(
            'users',
            sa.Column('oauth_id', sa.String(length=255), nullable=True)
        )

    # Add OAuth email (may differ from main email)
    if not _column_exists('users', 'oauth_email'):
        op.add_column(
            'users',
            sa.Column('oauth_email', sa.String(length=255), nullable=True)
        )

    # Add avatar URL
    if not _column_exists('users', 'avatar_url'):
        op.add_column(
            'users',
            sa.Column('avatar_url', sa.String(length=500), nullable=True)
        )

    # Make hashed_password nullable for OAuth-only users
    # Note: This requires special handling per database
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        op.alter_column(
            'users',
            'hashed_password',
            existing_type=sa.String(),
            nullable=True
        )
    elif dialect == 'sqlite':
        # SQLite doesn't support ALTER COLUMN, but nullable is already flexible
        pass

    # Create composite unique index for OAuth provider + ID
    if not _index_exists('users', 'ix_users_oauth_provider_id'):
        op.create_index(
            'ix_users_oauth_provider_id',
            'users',
            ['oauth_provider', 'oauth_id'],
            unique=True
        )


def downgrade():
    if not _table_exists('users'):
        return

    # Drop index first
    if _index_exists('users', 'ix_users_oauth_provider_id'):
        op.drop_index('ix_users_oauth_provider_id', table_name='users')

    # Make hashed_password required again
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == 'postgresql':
        # First update any NULL passwords to a placeholder
        op.execute(
            "UPDATE users SET hashed_password = 'OAUTH_USER_NO_PASSWORD' "
            "WHERE hashed_password IS NULL"
        )
        op.alter_column(
            'users',
            'hashed_password',
            existing_type=sa.String(),
            nullable=False
        )

    # Drop columns
    if _column_exists('users', 'avatar_url'):
        op.drop_column('users', 'avatar_url')

    if _column_exists('users', 'oauth_email'):
        op.drop_column('users', 'oauth_email')

    if _column_exists('users', 'oauth_id'):
        op.drop_column('users', 'oauth_id')

    if _column_exists('users', 'oauth_provider'):
        op.drop_column('users', 'oauth_provider')
