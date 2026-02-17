from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class CommitSourceExecutor(NodeExecutor):
    """Выполнение Source Node: Git Commit."""

    @staticmethod
    def _normalize_filters(raw_filters: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize UI aliases to canonical date_from/date_to filters."""
        filters = dict(raw_filters or {})

        if filters.get("after_date") and not filters.get("date_from"):
            filters["date_from"] = filters["after_date"]
        if filters.get("before_date") and not filters.get("date_to"):
            filters["date_to"] = filters["before_date"]

        return filters

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        filters = self._normalize_filters(data.get("filters", {}))

        query = context.db.query(Artifact).filter(Artifact.type == "commit")

        try:
            if filters.get("branch"):
                branch = InputValidator.validate_string(filters["branch"], "branch", max_length=500)
                query = query.filter(Artifact.meta["branch"].astext == branch)

            if filters.get("author"):
                author = InputValidator.validate_string(filters["author"], "author", max_length=500)
                query = query.filter(Artifact.meta["author"].astext == author)

            if filters.get("date_from"):
                date_from = InputValidator.validate_date(filters["date_from"], "date_from")
                query = query.filter(Artifact.created_at >= date_from)

            if filters.get("date_to"):
                date_to = InputValidator.validate_date(filters["date_to"], "date_to")
                query = query.filter(Artifact.created_at <= date_to)
        except ValueError as exc:
            context.add_error(f"Invalid filter in CommitSource: {str(exc)}")
            return []

        artifacts = query.all()
        context.set_node_output(node["id"], artifacts)

        return artifacts
