from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class JiraIssueSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Jira Issue."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        filters = data.get("filters", {})

        query = context.db.query(Artifact).filter(Artifact.type == "jira_issue")

        try:
            if filters.get("project"):
                project = InputValidator.validate_string(
                    filters["project"], "project", max_length=200
                )
                query = query.filter(Artifact.meta["project"].astext == project)

            if filters.get("issue_type"):
                issue_types = InputValidator.validate_list_of_strings(
                    filters["issue_type"],
                    "issue_type",
                    max_items=50,
                    max_item_length=200,
                )
                query = query.filter(Artifact.meta["issue_type"].astext.in_(issue_types))

            if filters.get("status"):
                statuses = InputValidator.validate_list_of_strings(
                    filters["status"],
                    "status",
                    max_items=50,
                    max_item_length=200,
                )
                query = query.filter(Artifact.meta["status"].astext.in_(statuses))
        except ValueError as exc:
            context.add_error(f"Invalid filter in JiraIssueSource: {str(exc)}")
            return []

        artifacts = query.all()
        context.set_node_output(node["id"], artifacts)

        return artifacts
