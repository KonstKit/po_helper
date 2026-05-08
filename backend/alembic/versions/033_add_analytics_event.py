"""add_analytics_event

Revision ID: 033_add_analytics_event
Revises: 032_add_execute_on_sync_complete_to_traceability_rules
Create Date: 2026-05-06

Adds analytics_event table to persist product usage analytics
(track / track-batch endpoints, onboarding & feature-adoption metrics).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "033_add_analytics_event"
down_revision = "032_add_execute_on_sync_complete_to_traceability_rules"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def upgrade() -> None:
    if _table_exists("analytics_event"):
        return

    op.create_table(
        "analytics_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_name", sa.String(length=128), nullable=False),
        sa.Column(
            "event_data",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("session_id", sa.String(length=128), nullable=True),
    )
    # `id` is already covered by the primary-key B-tree; no separate index.
    op.create_index(
        "ix_analytics_event_name_occurred",
        "analytics_event",
        ["event_name", "occurred_at"],
    )
    op.create_index(
        "ix_analytics_event_user_occurred",
        "analytics_event",
        ["user_id", "occurred_at"],
    )
    op.create_index(
        "ix_analytics_event_session",
        "analytics_event",
        ["session_id"],
    )


def downgrade() -> None:
    if not _table_exists("analytics_event"):
        return
    op.drop_index("ix_analytics_event_session", table_name="analytics_event")
    op.drop_index("ix_analytics_event_user_occurred", table_name="analytics_event")
    op.drop_index("ix_analytics_event_name_occurred", table_name="analytics_event")
    op.drop_table("analytics_event")
