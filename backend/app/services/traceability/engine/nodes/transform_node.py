from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor


class TransformNodeExecutor(NodeExecutor):
    """Processor Node: Transform artifacts."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        if not input_artifacts:
            context.add_warning(f"TransformNode {node['id']} received no input artifacts")
            context.set_node_output(node["id"], [])
            return []

        transform_type = config.get("transform_type", "passthrough")

        if transform_type == "passthrough":
            context.set_node_output(node["id"], input_artifacts)
            return input_artifacts

        context.add_warning(
            f"TransformNode {node['id']}: transform_type '{transform_type}' not yet implemented, passing through"
        )
        context.set_node_output(node["id"], input_artifacts)
        return input_artifacts
