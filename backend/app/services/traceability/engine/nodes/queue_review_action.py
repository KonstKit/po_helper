from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor


class QueueReviewActionExecutor(NodeExecutor):
    """Action Node: Queue artifacts for manual review."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        if not input_artifacts:
            context.add_warning(f"QueueReviewAction {node['id']} received no artifacts to review")
            return []

        review_reason = config.get("reason", "Manual review requested by traceability rule")
        priority = config.get("priority", "normal")

        for artifact in input_artifacts:
            context.add_warning(
                f"Review queued: {artifact.type} '{artifact.external_id or artifact.id}' "
                f"(priority: {priority}, reason: {review_reason})"
            )

        context.set_node_output(node["id"], [])
        return []
