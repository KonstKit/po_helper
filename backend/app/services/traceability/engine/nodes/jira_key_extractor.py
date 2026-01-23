from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class JiraKeyExtractorExecutor(NodeExecutor):
    """Выполнение Processor Node: Jira Key Extractor."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        try:
            search_in = config.get("search_in", ["message"])
            if not isinstance(search_in, list):
                search_in = [search_in]
            search_in = InputValidator.validate_list_of_strings(
                search_in,
                "search_in",
                max_items=10,
                max_item_length=50,
            )

            pattern = config.get("pattern", r"\b[A-Z][A-Z0-9_]+-[0-9]+\b")
            allow_custom = getattr(context, "allow_custom_regex", False)
            pattern = InputValidator.validate_regex_pattern(pattern, allow_custom=allow_custom)
        except ValueError as exc:
            context.add_error(f"Invalid config in JiraKeyExtractor: {str(exc)}")
            return []

        jira_keys = set()
        for artifact in input_artifacts:
            for field in search_in:
                text = self._get_field_value(artifact, field)
                if text:
                    try:
                        matches = re.findall(pattern, str(text))
                        jira_keys.update(matches)
                    except re.error as exc:
                        context.add_error(f"Regex execution error in JiraKeyExtractor: {str(exc)}")
                        continue

        if jira_keys:
            jira_artifacts = (
                context.db.query(Artifact)
                .filter(
                    Artifact.type == "jira_issue",
                    Artifact.external_id.in_(jira_keys),
                )
                .all()
            )
        else:
            jira_artifacts = []

        context.set_node_output(node["id"], jira_artifacts)
        return jira_artifacts

    def _get_field_value(self, artifact: Artifact, field: str) -> Optional[str]:
        """Получить значение поля из артефакта."""
        meta = artifact.meta or {}
        if field == "message" and artifact.type == "commit":
            return meta.get("message")
        if field == "branch" and artifact.type == "commit":
            return meta.get("branch")
        if field == "title":
            return artifact.title
        if field == "description":
            return meta.get("description")
        return None
