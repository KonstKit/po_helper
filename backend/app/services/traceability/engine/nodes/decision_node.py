from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.utils.confidence import normalize_confidence


class DecisionNodeExecutor(NodeExecutor):
    """Execution of Decision Node with branch-aware routing."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})
        node_id = node["id"]

        input_artifacts = context.get_input_artifacts(node_id)

        condition_type = config.get("condition_type", "count_threshold")
        threshold = config.get("threshold", 0)

        if condition_type == "confidence_threshold":
            true_artifacts, false_artifacts = self._split_by_confidence(input_artifacts, threshold)
            self._set_branch_outputs(node_id, context, true_artifacts, false_artifacts)
        else:
            result = self._evaluate_condition(input_artifacts, condition_type, threshold)
            true_artifacts = input_artifacts if result else []
            false_artifacts = input_artifacts if not result else []
            self._set_branch_outputs(node_id, context, true_artifacts, false_artifacts)

        # Keep legacy node output for downstream edges without explicit handles.
        context.set_node_output(node_id, input_artifacts)
        return input_artifacts

    def _set_branch_outputs(
        self,
        node_id: str,
        context: ExecutionContext,
        true_artifacts: List[Artifact],
        false_artifacts: List[Artifact],
    ) -> None:
        outgoing_edges = [edge for edge in context.edges if edge["source"] == node_id]

        for edge in outgoing_edges:
            handle_id = edge.get("sourceHandle", "true")
            if handle_id == "true":
                context.set_node_output_with_handle(node_id, handle_id, true_artifacts)
            elif handle_id == "false":
                context.set_node_output_with_handle(node_id, handle_id, false_artifacts)
            else:
                # Unknown handle id keeps backward compatibility with prior "true" default path.
                context.set_node_output_with_handle(node_id, handle_id, true_artifacts)

    def _split_by_confidence(
        self, artifacts: List[Artifact], threshold: Any
    ) -> Tuple[List[Artifact], List[Artifact]]:
        threshold_value = self._normalize_threshold(threshold)
        true_artifacts: List[Artifact] = []
        false_artifacts: List[Artifact] = []

        for artifact in artifacts:
            confidence_value = self._artifact_confidence(artifact)
            if confidence_value >= threshold_value:
                true_artifacts.append(artifact)
            else:
                false_artifacts.append(artifact)

        return true_artifacts, false_artifacts

    def _artifact_confidence(self, artifact: Artifact) -> float:
        # Artifact model does not guarantee a confidence field; check common sources.
        candidates = [getattr(artifact, "confidence", None)]
        meta = artifact.meta or {}
        candidates.extend(
            [
                meta.get("confidence"),
                meta.get("confidence_score"),
                meta.get("similarity_score"),
                meta.get("link_confidence"),
            ]
        )

        for raw_value in candidates:
            if raw_value is None:
                continue
            try:
                normalized = normalize_confidence(float(raw_value))
            except (TypeError, ValueError):
                normalized = None
            if normalized is not None:
                return normalized

        # Missing confidence is treated as 0 and routed to FALSE branch.
        return 0.0

    def _normalize_threshold(self, threshold: Any) -> float:
        try:
            raw_value = float(threshold)
        except (TypeError, ValueError):
            raw_value = 0.0

        # UI threshold is configured in percent by default.
        if raw_value > 1.0:
            raw_value = raw_value / 100.0

        return max(0.0, min(1.0, raw_value))

    def _evaluate_condition(
        self, artifacts: List[Artifact], condition_type: str, threshold: Any
    ) -> bool:
        """Evaluate legacy decision conditions for backward compatibility."""
        if condition_type == "count_threshold":
            try:
                threshold_value = int(threshold)
            except (TypeError, ValueError):
                threshold_value = 0
            return len(artifacts) >= threshold_value

        if condition_type == "count_equals":
            try:
                threshold_value = int(threshold)
            except (TypeError, ValueError):
                threshold_value = 0
            return len(artifacts) == threshold_value

        if condition_type == "has_artifacts":
            return len(artifacts) > 0

        if condition_type == "is_empty":
            return len(artifacts) == 0

        return True
