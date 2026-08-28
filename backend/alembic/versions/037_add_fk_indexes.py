"""add_missing_foreign_key_indexes

Revision ID: 037_add_fk_indexes
Revises: 036_add_trigger_source
Create Date: 2026-08-28

Adds indexes on foreign-key columns that the staff code review (wave A5)
found unindexed, so joins and cascading deletes stop seq-scanning:

- legacy_mappings.new_artifact_id
- suggested_links.from_artifact_id
- suggested_links.to_artifact_id
- artifacts.parent_version_id (self-FK)

Idempotent: each CREATE INDEX IF NOT EXISTS is a no-op when the index
already exists.
"""

from alembic import op
from sqlalchemy import text as sa_text


revision = "037_add_fk_indexes"
down_revision = "036_add_trigger_source"
branch_labels = None
depends_on = None


# (table, index_name, column)
_INDEXES = [
    ("legacy_mappings", "ix_legacy_mappings_new_artifact_id", "new_artifact_id"),
    ("suggested_links", "ix_suggested_links_from_artifact_id", "from_artifact_id"),
    ("suggested_links", "ix_suggested_links_to_artifact_id", "to_artifact_id"),
    ("artifacts", "ix_artifacts_parent_version_id", "parent_version_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    for table, index_name, column in _INDEXES:
        bind.execute(
            sa_text(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})"
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    for table, index_name, column in _INDEXES:
        bind.execute(sa_text(f"DROP INDEX IF EXISTS {index_name}"))
