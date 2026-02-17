from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from app.models.traceability import Artifact, ArtifactLink
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.link_service import REVERSE_LINK_TYPES

# Link types that enforce DAG (no cycles allowed)
DAG_LINK_TYPES = {"implements", "tests", "deploys", "derives_from"}


class CreateLinkActionExecutor(NodeExecutor):
    """Выполнение Action Node: Create Link."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        link_type = config.get("link_type", "relates_to")
        bidirectional = config.get("bidirectional", False)
        configured_reverse_type = config.get("reverse_link_type")
        reverse_link_type = None

        if bidirectional:
            reverse_link_type, used_fallback = self._resolve_reverse_link_type(
                link_type, configured_reverse_type
            )
            if used_fallback:
                context.add_warning(
                    f"CreateLinkAction: reverse_link_type not provided for '{link_type}', "
                    f"using fallback '{reverse_link_type}'"
                )

        incoming = context.incoming_edges.get(node["id"], [])

        if len(incoming) < 1:
            context.add_error(f"CreateLinkAction node {node['id']} has no inputs")
            return []

        if len(incoming) == 1:
            artifacts = context.get_input_artifacts(node["id"])
            self._create_self_links(
                artifacts, link_type, bidirectional, reverse_link_type, context
            )
        elif len(incoming) == 2:
            source_edge = incoming[0]
            target_edge = incoming[1]

            source_artifacts = self._get_artifacts_by_edge(source_edge, context)
            target_artifacts = self._get_artifacts_by_edge(target_edge, context)

            self._create_cross_links(
                source_artifacts,
                target_artifacts,
                link_type,
                bidirectional,
                reverse_link_type,
                context,
            )
        else:
            source_edge = incoming[0]
            source_artifacts = self._get_artifacts_by_edge(source_edge, context)

            for i in range(1, len(incoming)):
                target_artifacts = self._get_artifacts_by_edge(incoming[i], context)
                self._create_cross_links(
                    source_artifacts,
                    target_artifacts,
                    link_type,
                    bidirectional,
                    reverse_link_type,
                    context,
                )

        return []

    def _get_artifacts_by_edge(
        self, edge: Dict[str, Any], context: ExecutionContext
    ) -> List[Artifact]:
        """Get artifacts from a source edge, respecting sourceHandle for branching."""
        source_id = edge["source"]
        source_handle = edge.get("sourceHandle")

        # Try handle-specific output first (for DecisionNode branches)
        if source_handle:
            handle_key = f"{source_id}_{source_handle}"
            if handle_key in context.node_outputs:
                return context.node_outputs[handle_key]

        # Fall back to node output without handle
        return context.node_outputs.get(source_id, [])

    def _create_self_links(
        self,
        artifacts: List[Artifact],
        link_type: str,
        bidirectional: bool,
        reverse_link_type: str | None,
        context: ExecutionContext,
    ) -> None:
        for i, source in enumerate(artifacts):
            for target in artifacts[i + 1 :]:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    self._create_link(target, source, reverse_link_type or link_type, context)

    def _create_cross_links(
        self,
        sources: List[Artifact],
        targets: List[Artifact],
        link_type: str,
        bidirectional: bool,
        reverse_link_type: str | None,
        context: ExecutionContext,
    ) -> None:
        for source in sources:
            for target in targets:
                self._create_link(source, target, link_type, context)
                if bidirectional:
                    self._create_link(target, source, reverse_link_type or link_type, context)

    def _create_link(
        self,
        source: Artifact,
        target: Artifact,
        link_type: str,
        context: ExecutionContext,
        base_confidence: float = 0.90,
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

        # DAG cycle check for hierarchical link types
        if link_type in DAG_LINK_TYPES:
            if self._would_create_cycle(source.id, target.id, link_type, context):
                context.add_error(
                    f"Link would create cycle: {source.external_id} -[{link_type}]-> {target.external_id}"
                )
                return

        confidence = self._calculate_confidence(source, target, link_type, base_confidence, context)

        # Determine project_id from artifacts (prefer source)
        project_id = source.project_id or target.project_id

        link = ArtifactLink(
            from_artifact_id=source.id,
            to_artifact_id=target.id,
            link_type=link_type,
            confidence=confidence,
            project_id=project_id,
            created_via="rule",
            source_system="rule_engine",
            source_reference_id=str(context.rule_id),
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
        """Calculate confidence score (0.0-1.0 scale)."""
        confidence = base
        source_meta = source.meta or {}

        # Hierarchical links get full confidence
        if link_type in ["child_of", "parent_of"]:
            confidence = 1.0

        if source.external_id and target.external_id:
            if source.type == "commit" and target.type == "jira_issue":
                message = source_meta.get("message", "")
                if target.external_id in message:
                    # Boost if key is at the start of message
                    if message.startswith(target.external_id):
                        confidence += 0.10
                    confidence = min(1.0, confidence)

        if source.type == "commit":
            message = source_meta.get("message", "")
            jira_keys = re.findall(r"\b[A-Z][A-Z0-9_]+-[0-9]+\b", message)
            # Penalize if multiple keys (ambiguous reference)
            if len(jira_keys) > 1:
                confidence -= 0.05

        if source.type == "commit" and target.type == "jira_issue":
            branch = source_meta.get("branch", "")
            # Boost if key is in branch name
            if target.external_id in branch:
                confidence += 0.05

        return max(0.0, min(1.0, confidence))

    def _resolve_reverse_link_type(
        self, link_type: str, configured_reverse_type: str | None
    ) -> tuple[str, bool]:
        configured = (configured_reverse_type or "").strip()
        if configured:
            return configured, False
        return REVERSE_LINK_TYPES.get(link_type, f"reverse_{link_type}"), True

    def _get_reverse_link_type(self, link_type: str) -> str:
        """Backward-compatible helper kept for existing tests/imports."""
        return self._resolve_reverse_link_type(link_type, None)[0]

    def _would_create_cycle(
        self,
        from_id: int,
        to_id: int,
        link_type: str,
        context: ExecutionContext,
    ) -> bool:
        """Check if creating this link would create a cycle (BFS from to_id to from_id).

        Uses synchronous DB queries since rule engine runs in sync context.
        """
        visited: Set[int] = set()
        queue = [to_id]

        while queue:
            current = queue.pop(0)
            if current == from_id:
                return True

            if current in visited:
                continue
            visited.add(current)

            # Get outgoing links of same type (sync query)
            links = (
                context.db.query(ArtifactLink.to_artifact_id)
                .filter(
                    ArtifactLink.from_artifact_id == current,
                    ArtifactLink.link_type == link_type,
                )
                .all()
            )

            for (next_id,) in links:
                if next_id not in visited:
                    queue.append(next_id)

        return False
