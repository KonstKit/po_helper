from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class FilterNodeExecutor(NodeExecutor):
    """Выполнение Processor Node: Filter."""

    ALLOWED_OPERATORS = {"equals", "contains", "not_equals", "greater_than", "less_than"}

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        try:
            field = InputValidator.validate_string(config.get("field", ""), "field", max_length=200)
            operator = InputValidator.validate_string(
                config.get("operator", ""), "operator", max_length=50
            )

            if operator not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Operator must be one of: {', '.join(self.ALLOWED_OPERATORS)}")

            value = config.get("value")
            if isinstance(value, str):
                value = InputValidator.validate_string(value, "value", max_length=1000)
        except ValueError as exc:
            context.add_error(f"Invalid config in FilterNode: {str(exc)}")
            return []

        filtered_artifacts = []
        for artifact in input_artifacts:
            field_value = self._get_field_value(artifact, field)

            if self._apply_operator(field_value, operator, value):
                filtered_artifacts.append(artifact)

        context.set_node_output(node["id"], filtered_artifacts)
        return filtered_artifacts

    def _get_field_value(self, artifact: Artifact, field: str) -> Any:
        meta = artifact.meta or {}
        return meta.get(field)

    def _apply_operator(self, field_value: Any, operator: str, expected_value: Any) -> bool:
        if operator == "equals":
            return field_value == expected_value
        if operator == "contains":
            return expected_value in str(field_value)
        if operator == "not_equals":
            return field_value != expected_value
        if operator == "greater_than":
            try:
                return float(field_value) > float(expected_value)
            except (TypeError, ValueError):
                return False
        if operator == "less_than":
            try:
                return float(field_value) < float(expected_value)
            except (TypeError, ValueError):
                return False
        return False
