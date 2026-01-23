from __future__ import annotations

import re
from typing import Any, Dict, List

from app.models.traceability import Artifact, ArtifactLink
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor


class CreateLinkActionExecutor(NodeExecutor):
    """Выполнение Action Node: Create Link."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        link_type = config.get("link_type", "relates_to")
        bidirectional = config.get("bidirectional", False)

        incoming = context.incoming_edges.get(node["id"], [])

        if len(incoming) < 1:
            context.add_error(f"CreateLinkAction node {node['id']} has no inputs")
            return []

        if len(incoming) == 1:
            artifacts = context.get_input_artifacts(node["id"])
            self._create_self_links(artifacts, link_type, bidirectional, context)
        elif len(incoming) == 2:
            source_edge = incoming[0]
            target_edge = incoming[1]

            source_artifacts = context.node_outputs.get(source_edge["source"], [])
            target_artifacts = context.node_outputs.get(target_edge["source"], [])

            self._create_cross_links(
                source_artifacts, target_artifacts, link_type, bidirectional, context
            )
        else:
            source_edge = incoming[0]
            source_artifacts = context.node_outputs.get(source_edge["source"], [])

            for i in range(1, len(incoming)):
                target_artifacts = context.node_outputs.get(incoming[i]["source"], [])
                self._create_cross_links(
                    source_artifacts, target_artifacts, link_type, bidirectional, context
                )

        return []

    def _create_self_links(
        self,
        artifacts: List[Artifact],
        link_type: str,
        bidirectional: bool,
        context: ExecutionContext,
    ) -> None:
        for i, source in enumerate(artifacts):
            for target in artifacts[i + 1 :]:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    reverse_type = self._get_reverse_link_type(link_type)
                    self._create_link(target, source, reverse_type, context)

    def _create_cross_links(
        self,
        sources: List[Artifact],
        targets: List[Artifact],
        link_type: str,
        bidirectional: bool,
        context: ExecutionContext,
    ) -> None:
        for source in sources:
            for target in targets:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    reverse_type = self._get_reverse_link_type(link_type)
                    self._create_link(target, source, reverse_type, context)

    def _create_link(
        self,
        source: Artifact,
        target: Artifact,
        link_type: str,
        context: ExecutionContext,
        base_confidence: float = 90.0,
    ) -> None:
        existing = (
            context.db.query(ArtifactLink)
            .filter(
                ArtifactLink.from_artifact_id == source.id,
                ArtifactLink.to_artifact_id == target.id,
                ArtifactLink.link_type == link_type,
            )
            .first()
        )

        if existing:
            context.add_warning(
                f"Link already exists: {source.external_id} -> {target.external_id}"
            )
            return

        confidence = self._calculate_confidence(source, target, link_type, base_confidence, context)

        link = ArtifactLink(
            from_artifact_id=source.id,
            to_artifact_id=target.id,
            link_type=link_type,
            confidence=confidence,
        )

        context.db.add(link)
        context.add_link(link)

    def _calculate_confidence(
        self,
        source: Artifact,
        target: Artifact,
        link_type: str,
        base: float,
        context: ExecutionContext,
    ) -> float:
        confidence = base
        source_meta = source.meta or {}

        if link_type in ["child_of", "parent_of"]:
            confidence = 100.0

        if source.external_id and target.external_id:
            if source.type == "commit" and target.type == "jira_issue":
                message = source_meta.get("message", "")
                if target.external_id in message:
                    if message.startswith(target.external_id):
                        confidence += 10
                    confidence = min(100.0, confidence)

        if source.type == "commit":
            message = source_meta.get("message", "")
            jira_keys = re.findall(r"\b[A-Z][A-Z0-9_]+-[0-9]+\b", message)
            if len(jira_keys) > 1:
                confidence -= 5

        if source.type == "commit" and target.type == "jira_issue":
            branch = source_meta.get("branch", "")
            if target.external_id in branch:
                confidence += 5

        return max(0.0, min(100.0, confidence))

    def _get_reverse_link_type(self, link_type: str) -> str:
        reverse_map = {
            "implements": "implemented_by",
            "tests": "tested_by",
            "documents": "documented_by",
            "child_of": "parent_of",
            "depends_on": "required_by",
            "blocks": "blocked_by",
        }
        return reverse_map.get(link_type, f"reverse_{link_type}")
