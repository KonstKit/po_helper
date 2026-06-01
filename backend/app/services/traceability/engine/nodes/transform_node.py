from __future__ import annotations

from typing import Any, Dict, FrozenSet, List

from app.core.config import settings
from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor


SUPPORTED_TRANSFORM_TYPES: FrozenSet[str] = frozenset({"passthrough"})
DEFAULT_TRANSFORM_TYPE: str = "passthrough"


def is_supported_transform_type(transform_type: Any) -> bool:
    return isinstance(transform_type, str) and transform_type in SUPPORTED_TRANSFORM_TYPES


def format_unsupported_transform_message(transform_type: Any) -> str:
    supported = ", ".join(sorted(SUPPORTED_TRANSFORM_TYPES))
    return f"Unsupported transform_type {transform_type!r}; supported values: {supported}"


class TransformNodeExecutor(NodeExecutor):
    """Processor Node: Transform artifacts.

    Only modes in :data:`SUPPORTED_TRANSFORM_TYPES` are honored. Any other
    value produces a terminal execution error rather than silently passing
    artifacts through, so user configuration is trustworthy.
    """

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {}) or {}

        # Validate transform_type FIRST, before checking input.
        # An unsupported configuration must be terminal regardless of whether
        # the upstream branch produced artifacts on this run, so the contract
        # cannot be hidden by an empty input.
        #
        # `TRACEABILITY_TRANSFORM_STRICT` (default True) controls whether an
        # unsupported value raises or falls back to legacy warn+passthrough.
        # The flag exists for rolling deploys: if new code starts before
        # Alembic revision 034 rewrites legacy flow_json values, operators
        # can flip the flag to False, finish the migration, and flip it
        # back to True. See backend/app/core/config.py.
        transform_type = config.get("transform_type", DEFAULT_TRANSFORM_TYPE)
        if not is_supported_transform_type(transform_type):
            message = format_unsupported_transform_message(transform_type)
            if settings.TRACEABILITY_TRANSFORM_STRICT:
                raise ValueError(f"TransformNode {node['id']}: {message}")
            context.add_warning(
                f"TransformNode {node['id']}: {message} (strict mode disabled, "
                f"passing artifacts through)"
            )
            # Fall through to passthrough behavior below.

        input_artifacts = context.get_input_artifacts(node["id"])
        if not input_artifacts:
            context.add_warning(f"TransformNode {node['id']} received no input artifacts")
            context.set_node_output(node["id"], [])
            return []

        # Currently only 'passthrough' is supported.
        context.set_node_output(node["id"], input_artifacts)
        return input_artifacts
