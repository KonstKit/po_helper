"""add_mfa_security

Revision ID: 038_add_mfa_security
Revises: 037_add_fk_indexes
Create Date: 2026-08-28

Wave B of the Should Fix roadmap:

- users.mfa_secret widened String(64) -> String(512): it now stores an
  AES-GCM ciphertext (``encgcm:`` prefix + base64), which does not fit 64.
- users.mfa_last_used_counter added (Integer, nullable): TOTP interval of
  the most recently accepted code, used to reject replayed codes.

batch_alter_table keeps SQLite (no ALTER COLUMN) and PostgreSQL happy.
"""

import sqlalchemy as sa
from alembic import op


revision = "038_add_mfa_security"
down_revision = "037_add_fk_indexes"
branch_labels = None
depends_on = None


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
    with op.batch_alter_table("users") as batch:
        batch.drop_column("mfa_last_used_counter")
        batch.alter_column(
            "mfa_secret",
            existing_type=sa.String(512),
            type_=sa.String(64),
            existing_nullable=True,
        )
