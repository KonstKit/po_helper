"""Flow-graph validation for traceability rules (wave D1.1).

Extracted from the rules router: the router now only translates HTTP
concerns, while graph validation (structure, cycles, node configuration,
unsupported-type normalization) lives here and is unit-testable without
FastAPI. Mirrors frontend ruleValidation.ts.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException

from app.core.config import settings
from app.schemas.traceability_rule import (
    FlowJSON,
    ValidationError as ValidationErrorSchema,
    ValidationWarning as ValidationWarningSchema,
    ValidationResult,
)
from app.services.traceability.engine.nodes.transform_node import (
    SUPPORTED_TRANSFORM_TYPES,
    is_supported_transform_type,
)


# Node type classifications
SOURCE_NODE_TYPES = {
    "commitSource",
    "jiraIssueSource",
    "confluenceSource",
    "testrailSource",
    "manualSource",
}
ACTION_NODE_TYPES = {"createLinkAction", "queueReviewAction"}
PROCESSOR_NODE_TYPES = {"jiraKeyExtractor", "filterNode", "transformNode", "decisionNode"}


def validate_flow(flow_json: FlowJSON) -> ValidationResult:
    """
    Server-side validation of a traceability rule flow.
    Mirrors frontend ruleValidation.ts for consistency.
    """
    errors: list[ValidationErrorSchema] = []
    warnings: list[ValidationWarningSchema] = []
    nodes = flow_json.nodes
    edges = flow_json.edges

    # Rule 1: Must have at least one source node
    source_nodes = [n for n in nodes if n.type in SOURCE_NODE_TYPES]
    if not source_nodes:
        errors.append(
            ValidationErrorSchema(
                message="Rule must have at least one Source node (Commit, Jira Issue, Confluence, TestRail, or Manual)"
            )
        )

    # Rule 2: Must have at least one action node
    action_nodes = [n for n in nodes if n.type in ACTION_NODE_TYPES]
    if not action_nodes:
        errors.append(
            ValidationErrorSchema(
                message="Rule must have at least one Action node (Create Link, Queue Review, etc.)"
            )
        )

    # Rule 3: Check for disconnected nodes
    connected_node_ids = set()
    for edge in edges:
        connected_node_ids.add(edge.source)
        connected_node_ids.add(edge.target)

    for node in nodes:
        if node.id not in connected_node_ids and len(nodes) > 1:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Node "{label}" is not connected to any other nodes', node_id=node.id
                )
            )

    # Rule 4: Check for circular dependencies
    cycle = _detect_cycles(nodes, edges)
    if cycle:
        errors.append(
            ValidationErrorSchema(message=f"Circular dependency detected: {' → '.join(cycle)}")
        )

    # Rule 5: Validate source nodes have outputs
    for node in source_nodes:
        has_outgoing = any(e.source == node.id for e in edges)
        if not has_outgoing:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Source node "{label}" has no outgoing connections', node_id=node.id
                )
            )

    # Rule 6: Validate action nodes have inputs
    for node in action_nodes:
        has_incoming = any(e.target == node.id for e in edges)
        if not has_incoming:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Action node "{label}" has no incoming connections', node_id=node.id
                )
            )

    # Rule 7: Validate processor nodes have both inputs and outputs
    processor_nodes = [n for n in nodes if n.type in PROCESSOR_NODE_TYPES]
    for node in processor_nodes:
        has_incoming = any(e.target == node.id for e in edges)
        has_outgoing = any(e.source == node.id for e in edges)
        label = node.data.get("label", node.id)

        if not has_incoming:
            warnings.append(
                ValidationWarningSchema(
                    message=f'Processor node "{label}" has no input', node_id=node.id
                )
            )
        if not has_outgoing:
            warnings.append(
                ValidationWarningSchema(
                    message=f'Processor node "{label}" has no output', node_id=node.id
                )
            )

    # Rule 8: Validate node-specific configurations
    for node in nodes:
        node_errors, node_warnings = _validate_node_configuration(node)
        errors.extend(node_errors)
        warnings.extend(node_warnings)

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _detect_cycles(nodes, edges) -> list[str]:
    """Detect circular dependencies using DFS."""
    adjacency_list: dict[str, list[str]] = {n.id: [] for n in nodes}
    for edge in edges:
        if edge.source in adjacency_list:
            adjacency_list[edge.source].append(edge.target)

    visited = set()
    recursion_stack = set()
    cycle = []

    def dfs(node_id: str, path: list[str]) -> bool:
        nonlocal cycle
        visited.add(node_id)
        recursion_stack.add(node_id)
        path.append(node_id)

        for neighbor in adjacency_list.get(node_id, []):
            if neighbor not in visited:
                if dfs(neighbor, path):
                    return True
            elif neighbor in recursion_stack:
                # Cycle detected
                cycle_start_idx = path.index(neighbor)
                cycle = path[cycle_start_idx:]
                cycle.append(neighbor)
                return True

        recursion_stack.discard(node_id)
        path.pop()
        return False

    for node in nodes:
        if node.id not in visited:
            if dfs(node.id, []):
                # Convert node IDs to labels
                node_map = {n.id: n.data.get("label", n.id) for n in nodes}
                return [node_map.get(nid, nid) for nid in cycle]

    return []


def _validate_node_configuration(
    node,
) -> tuple[list[ValidationErrorSchema], list[ValidationWarningSchema]]:
    """Validate individual node configuration.

    Returns (errors, warnings). Most checks emit only errors; the transform
    contract emits a warning when ``TRACEABILITY_TRANSFORM_STRICT`` is off
    so legacy rules stay editable/executable during a rolling deploy that
    has not yet applied Alembic revision 034.
    """
    errors: list[ValidationErrorSchema] = []
    warnings: list[ValidationWarningSchema] = []
    node_type = node.type
    config = node.data.get("config", {})
    label = node.data.get("label", node.id)

    if node_type == "jiraKeyExtractor":
        search_in = config.get("search_in", [])
        if not search_in or (isinstance(search_in, list) and len(search_in) == 0):
            errors.append(
                ValidationErrorSchema(
                    message=f'Jira Key Extractor "{label}" must have at least one search field selected',
                    node_id=node.id,
                )
            )
        if not config.get("pattern"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Jira Key Extractor "{label}" must have a regex pattern',
                    node_id=node.id,
                )
            )

    elif node_type == "createLinkAction":
        if not config.get("link_type"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Create Link action "{label}" must have a link type', node_id=node.id
                )
            )
        if config.get("bidirectional") and not config.get("reverse_link_type"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Create Link action "{label}" with bidirectional enabled must specify reverse link type',
                    node_id=node.id,
                )
            )

    elif node_type == "filterNode":
        if not config.get("field"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Filter node "{label}" must specify a field to filter on',
                    node_id=node.id,
                )
            )
        if not config.get("operator"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Filter node "{label}" must specify an operator', node_id=node.id
                )
            )

    elif node_type == "transformNode":
        # transform_type is optional in the payload; absence implies the default
        # (passthrough). Only an explicit value outside the whitelist is rejected.
        # Strict mode mirrors runtime behavior: when the flag is off, legacy
        # values become a warning instead of a 400, so rules stored before
        # migration 034 stay editable/executable during the rollout window.
        if "transform_type" in config:
            transform_type = config.get("transform_type")
            if not is_supported_transform_type(transform_type):
                supported = ", ".join(sorted(SUPPORTED_TRANSFORM_TYPES))
                message = (
                    f'Transform node "{label}" has unsupported transform_type '
                    f'"{transform_type}"; supported values: {supported}'
                )
                if settings.TRACEABILITY_TRANSFORM_STRICT:
                    errors.append(ValidationErrorSchema(message=message, node_id=node.id))
                else:
                    warnings.append(
                        ValidationWarningSchema(
                            message=f"{message} (strict mode disabled, will pass through)",
                            node_id=node.id,
                        )
                    )

    elif node_type == "decisionNode":
        condition_type = config.get("condition_type", "count_threshold")
        supported_condition_types = {
            "confidence_threshold",
            "count_threshold",
            "count_equals",
            "has_artifacts",
            "is_empty",
        }
        if condition_type not in supported_condition_types:
            errors.append(
                ValidationErrorSchema(
                    message=(
                        f'Decision node "{label}" has unsupported condition_type '
                        f'"{condition_type}"'
                    ),
                    node_id=node.id,
                )
            )

        if condition_type == "confidence_threshold":
            threshold = config.get("threshold")
            if threshold is None:
                errors.append(
                    ValidationErrorSchema(
                        message=(
                            f'Decision node "{label}" with confidence_threshold '
                            "must provide a threshold"
                        ),
                        node_id=node.id,
                    )
                )
            else:
                try:
                    threshold_value = float(threshold)
                except (TypeError, ValueError):
                    errors.append(
                        ValidationErrorSchema(
                            message=(
                                f'Decision node "{label}" confidence threshold ' "must be numeric"
                            ),
                            node_id=node.id,
                        )
                    )
                else:
                    if not 0 <= threshold_value <= 100:
                        errors.append(
                            ValidationErrorSchema(
                                message=(
                                    f'Decision node "{label}" confidence threshold must '
                                    "be between 0 and 100"
                                ),
                                node_id=node.id,
                            )
                        )

    return errors, warnings


def _build_flow_validation_detail(
    validation_result: ValidationResult,
    *,
    code: str = "flow_validation_failed",
    message: str = "Flow validation failed",
) -> dict:
    return {
        "code": code,
        "message": message,
        "errors": [error.model_dump() for error in validation_result.errors],
        "warnings": [warning.model_dump() for warning in validation_result.warnings],
    }


def _ensure_flow_valid_or_400(flow_json: FlowJSON) -> ValidationResult:
    validation_result = validate_flow(flow_json)
    if not validation_result.valid:
        raise HTTPException(
            status_code=400,
            detail=_build_flow_validation_detail(validation_result),
        )
    return validation_result


def _normalize_unsupported_transform_types(flow_json: FlowJSON) -> bool:
    """Rewrite unsupported transform_type to passthrough in non-strict mode.

    Without this, a rule saved during the rollout window
    (TRACEABILITY_TRANSFORM_STRICT=False) would persist its unsupported
    value as-is and start failing as soon as strict mode is turned back
    on. Alembic revision 034 only rewrites rows that already existed, so
    save-time normalization is needed for new/updated rules. Mutates
    `flow_json.nodes` in place; no-op when strict mode is enabled.

    Returns True if any node was rewritten, so callers (notably the
    partial-update endpoint) can decide whether the normalized flow
    needs to be persisted back to the database even when the client
    only sent metadata fields.
    """
    if settings.TRACEABILITY_TRANSFORM_STRICT:
        return False
    rewritten = False
    audit_timestamp = datetime.now(timezone.utc).isoformat()
    for node in flow_json.nodes:
        if node.type != "transformNode":
            continue
        data = node.data or {}
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict) or "transform_type" not in config:
            continue
        value = config.get("transform_type")
        if is_supported_transform_type(value):
            continue
        config["transform_type"] = "passthrough"
        audit = config.setdefault("_legacy_transform_type_audit", {})
        audit["previous_value"] = value
        audit["rewritten_at"] = audit_timestamp
        audit["rewritten_by"] = (
            "api_v1/endpoints/traceability/rules.py:_normalize_unsupported_transform_types"
        )
        rewritten = True
    return rewritten
