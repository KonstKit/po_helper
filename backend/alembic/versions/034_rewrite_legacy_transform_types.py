"""rewrite_legacy_transform_types

Revision ID: 034_rewrite_legacy_transform_types
Revises: 033_add_analytics_event
Create Date: 2026-05-08

Rewrites traceability_rules.flow_json so any transformNode whose explicit
``transform_type`` falls outside the supported whitelist (currently
``{"passthrough"}``) is normalized to ``passthrough``. The previous value is
preserved under ``data.config._legacy_transform_type_audit`` for traceability.

This enforces the plan_69 transform behavior contract: by the time the new
runtime code runs, no persisted rule can land in the "raise on unsupported"
branch. The migration is idempotent — re-running it after a successful upgrade
finds nothing to rewrite. Downgrade is a no-op because the rewrite is
information-preserving (the audit field can be removed manually if desired).
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from alembic import op
import sqlalchemy as sa


revision = "034_rewrite_legacy_transform_types"
down_revision = "033_add_analytics_event"
branch_labels = None
depends_on = None


SUPPORTED_TRANSFORM_TYPES = frozenset({"passthrough"})
DEFAULT_TRANSFORM_TYPE = "passthrough"
AUDIT_KEY = "_legacy_transform_type_audit"


def _is_supported(value: Any) -> bool:
    return isinstance(value, str) and value in SUPPORTED_TRANSFORM_TYPES


def _coerce_flow(raw_flow: Any) -> Tuple[Dict[str, Any], bool]:
    if isinstance(raw_flow, str):
        try:
            return json.loads(raw_flow), True
        except json.JSONDecodeError:
            return {}, True
    if isinstance(raw_flow, dict):
        return raw_flow, False
    return {}, False


def _rewrite_flow(flow: Dict[str, Any], audit_timestamp: str) -> Tuple[Dict[str, Any], int]:
    """Return (new_flow, rewritten_count). Pure function — does not mutate input."""
    nodes = flow.get("nodes")
    if not isinstance(nodes, list):
        return flow, 0

    new_nodes = list(nodes)
    rewritten = 0

    for index, node in enumerate(new_nodes):
        if not isinstance(node, dict) or node.get("type") != "transformNode":
            continue
        data = node.get("data") or {}
        config = data.get("config") or {}
        if "transform_type" not in config:
            continue
        value = config.get("transform_type")
        if _is_supported(value):
            continue

        new_config = dict(config)
        new_config["transform_type"] = DEFAULT_TRANSFORM_TYPE
        audit = dict(new_config.get(AUDIT_KEY) or {})
        audit["previous_value"] = value
        audit["rewritten_at"] = audit_timestamp
        audit["rewritten_by"] = "alembic/034_rewrite_legacy_transform_types"
        new_config[AUDIT_KEY] = audit

        new_data = dict(data)
        new_data["config"] = new_config
        new_node = dict(node)
        new_node["data"] = new_data
        new_nodes[index] = new_node
        rewritten += 1

    if rewritten == 0:
        return flow, 0

    new_flow = dict(flow)
    new_flow["nodes"] = new_nodes
    return new_flow, rewritten


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "traceability_rules" not in inspector.get_table_names():
        return

    rules_table = sa.Table(
        "traceability_rules",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("flow_json", sa.JSON),
    )

    audit_timestamp = datetime.now(timezone.utc).isoformat()
    rows = bind.execute(sa.select(rules_table.c.id, rules_table.c.flow_json)).fetchall()

    for row in rows:
        rule_id = row[0]
        raw_flow = row[1]
        flow, was_string = _coerce_flow(raw_flow)
        if not flow:
            continue
        new_flow, rewritten = _rewrite_flow(flow, audit_timestamp)
        if rewritten == 0:
            continue
        new_value = json.dumps(new_flow) if was_string else new_flow
        bind.execute(
            sa.update(rules_table)
            .where(rules_table.c.id == rule_id)
            .values(flow_json=new_value)
        )


def downgrade() -> None:
    # The rewrite is information-preserving (the previous value is kept in
    # data.config._legacy_transform_type_audit). A general downgrade cannot
    # know which audit entries belong to this migration, so we leave both
    # the rewritten transform_type and the audit field in place.
    pass
