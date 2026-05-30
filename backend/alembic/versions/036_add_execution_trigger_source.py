"""add_execution_trigger_source

Revision ID: 036_add_trigger_source
Revises: 035_add_review_items
Create Date: 2026-05-30

Adds ``traceability_rule_executions.trigger_source`` so execution history can
record what initiated each run: manual | webhook | scheduled | post_sync
(plan_76 Step 4). Nullable — pre-existing rows keep NULL ("unknown").

Idempotent: re-running upgrade after a partial apply is a no-op if the column
already exists. SQLite/offline validated in-session; PostgreSQL validation is
handed off.
"""

from alembic import op
import sqlalchemy as sa


revision = "036_add_trigger_source"
down_revision = "035_add_review_items"
branch_labels = None
depends_on = None


_TABLE = "traceability_rule_executions"
_COLUMN = "trigger_source"


def _has_column(bind) -> bool:
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    return _COLUMN in cols


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    if not _has_column(bind):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=32), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    if _has_column(bind):
        op.drop_column(_TABLE, _COLUMN)
