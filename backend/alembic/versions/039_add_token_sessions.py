"""add_token_sessions (JWT storage migration M3)

Revision ID: 039_add_token_sessions
Revises: 038_add_mfa_security
Create Date: 2026-09-05

Server-side refresh-token sessions (RFC_JWT_STORAGE.md step M3):

- token_sessions: one row per issued refresh token (SHA-256 digest,
  never the plaintext), with expiry, revocation and last-use tracking.
- Rotation revokes the old row and issues a new one; logout revokes
  the caller session; password change revokes all sessions of the user.

Downgrade drops the table (all refresh sessions are invalidated;
  users simply sign in again).
"""

import sqlalchemy as sa
from alembic import op


revision = "039_add_token_sessions"
down_revision = "038_add_mfa_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("refresh_token_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("token_sessions")
