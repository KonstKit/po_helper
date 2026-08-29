"""Tests for the transform behavior contract (plan_69).

Covers:
- TransformNodeExecutor: passthrough, default value, empty input, unsupported.
- validate_flow save-time validation: accepts whitelist, rejects unsupported.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.api.api_v1.endpoints.traceability.rules import validate_flow
from app.schemas.traceability_rule import FlowJSON
from app.services.traceability.engine.nodes.transform_node import (
    SUPPORTED_TRANSFORM_TYPES,
    TransformNodeExecutor,
    is_supported_transform_type,
)


class _ContextStub:
    def __init__(self, input_artifacts: List[Any]):
        self._input_artifacts = input_artifacts
        self.node_outputs: Dict[str, List[Any]] = {}
        self.warnings: List[str] = []

    def get_input_artifacts(self, _node_id: str) -> List[Any]:
        return self._input_artifacts

    def set_node_output(self, node_id: str, artifacts: List[Any]) -> None:
        self.node_outputs[node_id] = artifacts

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def _build_flow(transform_config: Dict[str, Any]) -> FlowJSON:
    """Build a minimal valid flow with a single transformNode between source and action."""
    return FlowJSON.model_validate(
        {
            "nodes": [
                {
                    "id": "src",
                    "type": "manualSource",
                    "position": {"x": 0, "y": 0},
                    "data": {"label": "Source", "config": {"artifact_ids": [1]}},
                },
                {
                    "id": "tx",
                    "type": "transformNode",
                    "position": {"x": 100, "y": 0},
                    "data": {"label": "Transform", "config": transform_config},
                },
                {
                    "id": "act",
                    "type": "createLinkAction",
                    "position": {"x": 200, "y": 0},
                    "data": {"label": "Link", "config": {"link_type": "relates_to"}},
                },
            ],
            "edges": [
                {"id": "e1", "source": "src", "target": "tx"},
                {"id": "e2", "source": "tx", "target": "act"},
            ],
        }
    )


# -----------------------------
# Executor-level contract
# -----------------------------


def test_passthrough_returns_input_artifacts():
    executor = TransformNodeExecutor()
    artifacts = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    context = _ContextStub(artifacts)

    result = executor.execute(
        {"id": "tx", "data": {"config": {"transform_type": "passthrough"}}}, context
    )

    assert result == artifacts
    assert context.node_outputs["tx"] == artifacts
    assert context.warnings == []


def test_missing_transform_type_defaults_to_passthrough():
    executor = TransformNodeExecutor()
    artifacts = [SimpleNamespace(id=1)]
    context = _ContextStub(artifacts)

    result = executor.execute({"id": "tx", "data": {"config": {}}}, context)

    assert result == artifacts


def test_missing_config_dict_defaults_to_passthrough():
    executor = TransformNodeExecutor()
    artifacts = [SimpleNamespace(id=1)]
    context = _ContextStub(artifacts)

    result = executor.execute({"id": "tx", "data": {}}, context)

    assert result == artifacts


def test_empty_input_returns_empty_with_warning():
    executor = TransformNodeExecutor()
    context = _ContextStub([])

    result = executor.execute(
        {"id": "tx", "data": {"config": {"transform_type": "passthrough"}}}, context
    )

    assert result == []
    assert context.node_outputs["tx"] == []
    assert any("received no input artifacts" in w for w in context.warnings)


@pytest.mark.parametrize(
    "transform_type",
    ["uppercase", "to_jira", "PASSTHROUGH", "", None, 42],
)
def test_unsupported_transform_type_raises(transform_type: Any):
    executor = TransformNodeExecutor()
    artifacts = [SimpleNamespace(id=1)]
    context = _ContextStub(artifacts)

    with pytest.raises(ValueError) as excinfo:
        executor.execute(
            {"id": "tx", "data": {"config": {"transform_type": transform_type}}}, context
        )

    assert "TransformNode tx" in str(excinfo.value)
    assert "passthrough" in str(excinfo.value)
    # Output must not be set when execution rejects the configuration.
    assert "tx" not in context.node_outputs


def test_strict_mode_disabled_falls_back_to_warn_and_passthrough(monkeypatch):
    """Rolling-deploy safety: TRACEABILITY_TRANSFORM_STRICT=False mirrors pre-plan_69 behavior."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TRACEABILITY_TRANSFORM_STRICT", False)
    executor = TransformNodeExecutor()
    artifacts = [SimpleNamespace(id=1)]
    context = _ContextStub(artifacts)

    result = executor.execute(
        {"id": "tx", "data": {"config": {"transform_type": "uppercase"}}}, context
    )

    assert result == artifacts
    assert context.node_outputs["tx"] == artifacts
    assert any("uppercase" in w for w in context.warnings)
    assert any("strict mode disabled" in w for w in context.warnings)


def test_unsupported_transform_type_raises_even_on_empty_input():
    """Empty upstream branch must not hide an unsupported transform_type."""
    executor = TransformNodeExecutor()
    context = _ContextStub([])

    with pytest.raises(ValueError) as excinfo:
        executor.execute({"id": "tx", "data": {"config": {"transform_type": "uppercase"}}}, context)

    assert "TransformNode tx" in str(excinfo.value)
    assert "passthrough" in str(excinfo.value)
    # Output must NOT be set and the empty-input warning must NOT be issued —
    # validation runs first and short-circuits the rest of the executor.
    assert "tx" not in context.node_outputs
    assert context.warnings == []


def test_supported_set_is_locked_to_passthrough():
    assert SUPPORTED_TRANSFORM_TYPES == frozenset({"passthrough"})
    assert is_supported_transform_type("passthrough") is True
    assert is_supported_transform_type("custom") is False
    assert is_supported_transform_type(None) is False


# -----------------------------
# Save-time validation contract
# -----------------------------


def test_validate_flow_accepts_passthrough():
    flow = _build_flow({"transform_type": "passthrough"})

    result = validate_flow(flow)

    assert result.valid is True
    assert all("Transform node" not in error.message for error in result.errors)


def test_validate_flow_accepts_missing_transform_type():
    flow = _build_flow({})

    result = validate_flow(flow)

    assert result.valid is True
    assert all("Transform node" not in error.message for error in result.errors)


def test_normalize_rewrites_unsupported_to_passthrough_in_non_strict(monkeypatch):
    """Save-time normalization closes the rollout-window hole: rules saved
    with an unsupported transform_type are rewritten to passthrough so a
    later strict-mode flip does not break them."""
    from app.api.api_v1.endpoints.traceability.rules import (
        _normalize_unsupported_transform_types,
    )
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TRACEABILITY_TRANSFORM_STRICT", False)
    flow = _build_flow({"transform_type": "uppercase"})

    _normalize_unsupported_transform_types(flow)

    transform_node = next(n for n in flow.nodes if n.type == "transformNode")
    config = transform_node.data["config"]
    assert config["transform_type"] == "passthrough"
    audit = config["_legacy_transform_type_audit"]
    assert audit["previous_value"] == "uppercase"
    assert "rewritten_at" in audit
    assert "_normalize_unsupported_transform_types" in audit["rewritten_by"]


def test_normalize_is_noop_in_strict_mode():
    """Strict mode keeps the value as-is (and validation rejects it)."""
    from app.api.api_v1.endpoints.traceability.rules import (
        _normalize_unsupported_transform_types,
    )

    flow = _build_flow({"transform_type": "uppercase"})

    _normalize_unsupported_transform_types(flow)

    transform_node = next(n for n in flow.nodes if n.type == "transformNode")
    assert transform_node.data["config"]["transform_type"] == "uppercase"
    assert "_legacy_transform_type_audit" not in transform_node.data["config"]


def test_normalize_leaves_supported_passthrough_untouched(monkeypatch):
    from app.api.api_v1.endpoints.traceability.rules import (
        _normalize_unsupported_transform_types,
    )
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TRACEABILITY_TRANSFORM_STRICT", False)
    flow = _build_flow({"transform_type": "passthrough"})

    _normalize_unsupported_transform_types(flow)

    transform_node = next(n for n in flow.nodes if n.type == "transformNode")
    assert transform_node.data["config"]["transform_type"] == "passthrough"
    assert "_legacy_transform_type_audit" not in transform_node.data["config"]


def test_validate_flow_demotes_to_warning_when_strict_disabled(monkeypatch):
    """Rolling-deploy escape hatch: TRACEABILITY_TRANSFORM_STRICT=False keeps
    legacy rules editable/executable until migration 034 runs."""
    from app.core.config import settings as app_settings

    monkeypatch.setattr(app_settings, "TRACEABILITY_TRANSFORM_STRICT", False)
    flow = _build_flow({"transform_type": "uppercase"})

    result = validate_flow(flow)

    assert result.valid is True  # No errors → flow can still be saved/executed.
    transform_warnings = [w for w in result.warnings if "Transform node" in w.message]
    assert len(transform_warnings) == 1
    assert transform_warnings[0].node_id == "tx"
    assert "uppercase" in transform_warnings[0].message
    assert "strict mode disabled" in transform_warnings[0].message


def test_validate_flow_rejects_unsupported_transform_type():
    flow = _build_flow({"transform_type": "uppercase"})

    result = validate_flow(flow)

    assert result.valid is False
    transform_errors = [e for e in result.errors if "Transform node" in e.message]
    assert len(transform_errors) == 1
    assert transform_errors[0].node_id == "tx"
    assert "uppercase" in transform_errors[0].message
    assert "passthrough" in transform_errors[0].message


def test_validate_flow_rejects_non_string_transform_type():
    flow = _build_flow({"transform_type": 123})

    result = validate_flow(flow)

    assert result.valid is False
    transform_errors = [e for e in result.errors if "Transform node" in e.message]
    assert len(transform_errors) == 1
    assert transform_errors[0].node_id == "tx"
