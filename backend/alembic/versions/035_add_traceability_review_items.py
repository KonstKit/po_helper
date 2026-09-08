"""add_traceability_review_items

Revision ID: 035_add_review_items
Revises: 034_rewrite_legacy_types
Create Date: 2026-05-29

Adds the ``traceability_review_items`` table backing the manual-review queue
(plan_70). The ``queueReviewAction`` rule node persists durable review work
items here instead of emitting transient execution warnings.

Deduplication is enforced by a partial unique index over
``(project_id, artifact_id, rule_id, node_id)`` while the item is *open*
(status pending/claimed), so reruns refresh the open item rather than piling
up duplicates. Both SQLite and PostgreSQL support partial indexes.

Downgrade drops the indexes before the table (plan_70 step 2B). SQLite/offline
validation was performed in-session; PostgreSQL upgrade/rollback was validated
on a live PostgreSQL 15 database (2026-09-08, two full 039 -> 034 -> 039
cycles — see TRACEABILITY_BACKEND_VALIDATION.md).
"""

from alembic import op
import sqlalchemy as sa


revision = "035_add_review_items"
down_revision = "034_rewrite_legacy_types"
branch_labels = None
depends_on = None


_TABLE = "traceability_review_items"
_OPEN_INDEX = "uq_traceability_review_items_open"
_STATUS_INDEX = "ix_traceability_review_items_status_project"
_OPEN_PREDICATE = "status IN ('pending', 'claimed')"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_exists = _TABLE in inspector.get_table_names()

    if not table_exists:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.String(), nullable=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column(
                "artifact_id", sa.Integer(), sa.ForeignKey("artifacts.id"), nullable=False
            ),
            sa.Column(
                "rule_id",
                sa.Integer(),
                sa.ForeignKey("traceability_rules.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "rule_execution_id",
                sa.Integer(),
                sa.ForeignKey("traceability_rule_executions.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("node_id", sa.String(length=128), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("priority", sa.String(length=32), nullable=False, server_default="normal"),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # (Re)create any missing indexes individually instead of bailing out when
    # the table already exists. This lets a partially-applied migration (table
    # created but an index creation aborted) be repaired by re-running upgrade,
    # so the dedup partial unique index is never silently left absent.
    existing_indexes = (
        {ix["name"] for ix in sa.inspect(bind).get_indexes(_TABLE)}
        if table_exists
        else set()
    )

    def _ensure_index(name, columns, **kwargs):
        if name not in existing_indexes:
            op.create_index(name, _TABLE, columns, **kwargs)

    _ensure_index("ix_traceability_review_items_tenant_id", ["tenant_id"])
    _ensure_index("ix_traceability_review_items_project_id", ["project_id"])
    _ensure_index("ix_traceability_review_items_artifact_id", ["artifact_id"])
    _ensure_index("ix_traceability_review_items_rule_id", ["rule_id"])
    _ensure_index(_STATUS_INDEX, ["project_id", "status", "priority"])
    _ensure_index(
        _OPEN_INDEX,
        ["project_id", "artifact_id", "rule_id", "node_id"],
        unique=True,
        sqlite_where=sa.text(_OPEN_PREDICATE),
        postgresql_where=sa.text(_OPEN_PREDICATE),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    # Drop indexes before the table (plan_70 step 2B rollback contract).
    for index_name in (
        _OPEN_INDEX,
        _STATUS_INDEX,
        "ix_traceability_review_items_rule_id",
        "ix_traceability_review_items_artifact_id",
        "ix_traceability_review_items_project_id",
        "ix_traceability_review_items_tenant_id",
    ):
        try:
            op.drop_index(index_name, table_name=_TABLE)
        except Exception:
            # Index may not exist on partially-applied schemas; keep going.
            pass

    op.drop_table(_TABLE)
