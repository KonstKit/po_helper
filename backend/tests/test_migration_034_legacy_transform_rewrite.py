"""Unit tests for the pure rewrite logic of migration 034.

The migration touches DB rows, but its core decision is encapsulated in the
pure ``_rewrite_flow`` function. We test that here so the data step has
explicit acceptance evidence without spinning up Alembic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_migration_module():
    """Load the 034_* revision file as a Python module."""
    revision_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "034_rewrite_legacy_transform_types.py"
    )
    spec = importlib.util.spec_from_file_location(
        "alembic_034_rewrite_legacy_transform_types", revision_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


migration = _load_migration_module()
TS = "2026-05-08T00:00:00+00:00"


def _flow(*nodes):
    return {"nodes": list(nodes), "edges": []}


def _node(node_id, transform_type=None, *, omit_config=False):
    if omit_config:
        return {"id": node_id, "type": "transformNode", "data": {}}
    config = {} if transform_type is None else {"transform_type": transform_type}
    return {"id": node_id, "type": "transformNode", "data": {"config": config}}


def test_rewrites_unsupported_to_passthrough_with_audit():
    flow = _flow(_node("tx1", "uppercase"))

    new_flow, count = migration._rewrite_flow(flow, TS)

    assert count == 1
    config = new_flow["nodes"][0]["data"]["config"]
    assert config["transform_type"] == "passthrough"
    audit = config[migration.AUDIT_KEY]
    assert audit["previous_value"] == "uppercase"
    assert audit["rewritten_at"] == TS
    assert audit["rewritten_by"] == "alembic/034_rewrite_legacy_transform_types"


def test_passthrough_is_left_untouched():
    flow = _flow(_node("tx1", "passthrough"))

    new_flow, count = migration._rewrite_flow(flow, TS)

    assert count == 0
    assert new_flow is flow  # short-circuit, no copy
    assert "_legacy_transform_type_audit" not in flow["nodes"][0]["data"]["config"]


def test_missing_transform_type_is_left_untouched():
    flow = _flow(_node("tx1", omit_config=True))
    new_flow, count = migration._rewrite_flow(flow, TS)
    assert count == 0
    assert new_flow is flow


def test_rewrite_does_not_mutate_input():
    flow = _flow(_node("tx1", "uppercase"))
    original_config = flow["nodes"][0]["data"]["config"]
    snapshot = dict(original_config)

    migration._rewrite_flow(flow, TS)

    assert flow["nodes"][0]["data"]["config"] == snapshot
    assert "_legacy_transform_type_audit" not in original_config


def test_idempotent_after_rewrite():
    flow = _flow(_node("tx1", "uppercase"))
    once, count_once = migration._rewrite_flow(flow, TS)
    twice, count_twice = migration._rewrite_flow(once, TS)

    assert count_once == 1
    assert count_twice == 0
    assert twice is once  # second pass short-circuits, no further mutation


def test_handles_multiple_nodes_and_unrelated_types():
    flow = _flow(
        _node("tx1", "uppercase"),
        {"id": "filter_a", "type": "filterNode", "data": {"config": {"field": "x"}}},
        _node("tx2", "passthrough"),
        _node("tx3", "to_jira"),
    )

    new_flow, count = migration._rewrite_flow(flow, TS)

    assert count == 2
    types = [n["data"]["config"].get("transform_type") for n in new_flow["nodes"] if n["type"] == "transformNode"]
    assert types == ["passthrough", "passthrough", "passthrough"]
    # Filter node config preserved unchanged.
    filter_config = new_flow["nodes"][1]["data"]["config"]
    assert filter_config == {"field": "x"}


def test_handles_non_string_transform_type():
    flow = _flow(_node("tx1", 42))

    new_flow, count = migration._rewrite_flow(flow, TS)

    assert count == 1
    config = new_flow["nodes"][0]["data"]["config"]
    assert config["transform_type"] == "passthrough"
    assert config[migration.AUDIT_KEY]["previous_value"] == 42


def test_handles_empty_or_missing_nodes():
    assert migration._rewrite_flow({"nodes": [], "edges": []}, TS) == ({"nodes": [], "edges": []}, 0)
    assert migration._rewrite_flow({"edges": []}, TS) == ({"edges": []}, 0)


def test_coerce_flow_handles_string_and_dict_and_garbage():
    assert migration._coerce_flow({"nodes": []}) == ({"nodes": []}, False)
    parsed, was_string = migration._coerce_flow('{"nodes": []}')
    assert parsed == {"nodes": []}
    assert was_string is True
    assert migration._coerce_flow("not-json") == ({}, True)
    assert migration._coerce_flow(42) == ({}, False)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("passthrough", True),
        ("PASSTHROUGH", False),
        ("uppercase", False),
        ("", False),
        (None, False),
        (123, False),
    ],
)
def test_is_supported(value, expected):
    assert migration._is_supported(value) is expected
