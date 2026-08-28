"""add_mfa_security

Revision ID: 038_add_mfa_security
Revises: 037_add_fk_indexes
Create Date: 2026-08-28

Wave B of the Should Fix roadmap:

- users.mfa_secret widened String(64) -> String(512): it now stores an
  AES-GCM ciphertext (``encgcm:`` prefix + base64), which does not fit 64.
- users.mfa_last_used_counter added (Integer, nullable): TOTP interval of
  the most recently accepted code, used to reject replayed codes.

Downgrade policy: REFUSES to run while wave-B data exists. Encrypted
secrets no longer fit String(64) (PostgreSQL cannot shrink the column),
and bcrypt backup-code digests cannot be turned back into plaintext.
Disable MFA for all accounts first (mfa_enabled=false, mfa_secret=NULL,
mfa_backup_codes=NULL), then downgrade.

batch_alter_table keeps SQLite (no ALTER COLUMN) and PostgreSQL happy.
"""

import sqlalchemy as sa
from alembic import op


revision = "038_add_mfa_security"
down_revision = "037_add_fk_indexes"
branch_labels = None
depends_on = None


def _wave_b_data_exists(bind) -> bool:
    """True only for data this migration cannot undo: encrypted secrets
    (longer than String(64)) and bcrypt backup-code digests. Legacy
    plaintext codes fit the old schema and do not block the downgrade."""
    result = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM users "
            "WHERE mfa_secret LIKE 'encgcm:%' "
            "   OR mfa_backup_codes LIKE '%$2%')"
        )
    )
    return bool(result.scalar())


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "mfa_secret",
            existing_type=sa.String(64),
            type_=sa.String(512),
            existing_nullable=True,
        )
        batch.add_column(sa.Column("mfa_last_used_counter", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _wave_b_data_exists(bind):
        raise RuntimeError(
            "Cannot downgrade 038_add_mfa_security while wave-B MFA data "
            "exists: encrypted secrets do not fit String(64) and bcrypt "
            "backup-code digests are not reversible. Disable MFA for all "
            "accounts first (mfa_enabled=false, mfa_secret=NULL, "
            "mfa_backup_codes=NULL), then re-run the downgrade."
        )
    with op.batch_alter_table("users") as batch:
        batch.drop_column("mfa_last_used_counter")
        batch.alter_column(
            "mfa_secret",
            existing_type=sa.String(512),
            type_=sa.String(64),
            existing_nullable=True,
        )
