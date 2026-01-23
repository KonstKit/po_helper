from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor


class DecisionNodeExecutor(NodeExecutor):
    """Выполнение Decision Node: условное ветвление."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        condition_type = config.get("condition_type", "count_threshold")
        threshold = config.get("threshold", 0)

        result = self._evaluate_condition(input_artifacts, condition_type, threshold)

        outgoing_edges = [e for e in context.edges if e["source"] == node["id"]]

        for edge in outgoing_edges:
            handle_id = edge.get("sourceHandle", "true")

            if (result and handle_id == "true") or (not result and handle_id == "false"):
                context.set_node_output(node["id"] + "_" + handle_id, input_artifacts)
            else:
                context.set_node_output(node["id"] + "_" + handle_id, [])

        context.set_node_output(node["id"], input_artifacts)
        return input_artifacts

    def _evaluate_condition(
        self, artifacts: List[Artifact], condition_type: str, threshold: Any
    ) -> bool:
        """Вычислить условие."""
        if condition_type == "count_threshold":
            return len(artifacts) >= int(threshold)
        if condition_type == "count_equals":
            return len(artifacts) == int(threshold)
        if condition_type == "has_artifacts":
            return len(artifacts) > 0
        if condition_type == "is_empty":
            return len(artifacts) == 0
        return True
