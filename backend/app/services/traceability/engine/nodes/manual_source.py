from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class ManualArtifactSourceExecutor(NodeExecutor):
    """Source Node for manually defined artifact collections."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        try:
            artifact_ids = config.get("artifact_ids", [])
            if artifact_ids:
                if not isinstance(artifact_ids, list):
                    artifact_ids = [artifact_ids]
                validated_ids = []
                for aid in artifact_ids:
                    try:
                        validated_ids.append(int(aid))
                    except (ValueError, TypeError):
                        context.add_warning(f"Invalid artifact ID: {aid}")
                        continue

                if validated_ids:
                    artifacts = (
                        context.db.query(Artifact).filter(Artifact.id.in_(validated_ids)).all()
                    )
                    context.set_node_output(node["id"], artifacts)
                    return artifacts

            external_ids = config.get("external_ids", [])
            if external_ids:
                external_ids = InputValidator.validate_list_of_strings(
                    external_ids,
                    "external_ids",
                    max_items=500,
                    max_item_length=200,
                )
                artifacts = (
                    context.db.query(Artifact).filter(Artifact.external_id.in_(external_ids)).all()
                )
                context.set_node_output(node["id"], artifacts)
                return artifacts

            artifact_types = config.get("artifact_types", [])
            if artifact_types:
                artifact_types = InputValidator.validate_list_of_strings(
                    artifact_types,
                    "artifact_types",
                    max_items=20,
                    max_item_length=50,
                )
                query = context.db.query(Artifact).filter(Artifact.type.in_(artifact_types))

                if config.get("project_id"):
                    query = query.filter(Artifact.project_id == int(config["project_id"]))

                if config.get("tags"):
                    tags = InputValidator.validate_list_of_strings(
                        config["tags"],
                        "tags",
                        max_items=20,
                        max_item_length=100,
                    )
                    for tag in tags:
                        query = query.filter(Artifact.meta["tags"].astext.contains(tag))

                artifacts = query.all()
                context.set_node_output(node["id"], artifacts)
                return artifacts

        except ValueError as exc:
            context.add_error(f"Invalid config in ManualArtifactSource: {str(exc)}")
            return []

        context.add_warning(f"ManualArtifactSource node {node['id']} returned no artifacts")
        context.set_node_output(node["id"], [])
        return []
