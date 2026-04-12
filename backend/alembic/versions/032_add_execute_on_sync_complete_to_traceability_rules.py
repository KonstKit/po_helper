"""add_execute_on_sync_complete_to_traceability_rules

Revision ID: 032_add_execute_on_sync_complete_to_traceability_rules
Revises: 031_add_running_sync_task_unique_lease
Create Date: 2026-04-12

Adds execute_on_sync_complete flag to traceability_rules so rules can opt in
to batch execution after artifact ingestion completes.
"""

from alembic import op
import sqlalchemy as sa


revision = "032_add_execute_on_sync_complete_to_traceability_rules"
down_revision = "031_add_running_sync_task_unique_lease"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    if not _column_exists("traceability_rules", "execute_on_sync_complete"):
        op.add_column(
            "traceability_rules",
            sa.Column(
                "execute_on_sync_complete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
        )


def downgrade() -> None:
    if _column_exists("traceability_rules", "execute_on_sync_complete"):
        op.drop_column("traceability_rules", "execute_on_sync_complete")
