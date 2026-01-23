from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class ConfluenceSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Confluence Page."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        filters = data.get("filters", {})

        query = context.db.query(Artifact).filter(Artifact.type == "confluence_page")

        try:
            if filters.get("space"):
                space = InputValidator.validate_string(filters["space"], "space", max_length=200)
                query = query.filter(Artifact.meta["space"].astext == space)

            if filters.get("labels"):
                labels = InputValidator.validate_list_of_strings(
                    filters["labels"],
                    "labels",
                    max_items=50,
                    max_item_length=200,
                )
                for label in labels:
                    query = query.filter(Artifact.meta["labels"].astext.contains(label))
        except ValueError as exc:
            context.add_error(f"Invalid filter in ConfluenceSource: {str(exc)}")
            return []

        artifacts = query.all()
        context.set_node_output(node["id"], artifacts)

        return artifacts
