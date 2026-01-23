from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor
from app.services.traceability.engine.validators import InputValidator


class TestRailSourceExecutor(NodeExecutor):
    """Source Node for TestRail test cases and test runs."""

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        filters = data.get("filters", {})

        query = context.db.query(Artifact).filter(
            Artifact.type.in_(["testrail_test", "testrail_case", "testrail_run"])
        )

        try:
            if filters.get("project_id"):
                project_id = InputValidator.validate_string(
                    str(filters["project_id"]),
                    "project_id",
                    max_length=100,
                )
                query = query.filter(Artifact.meta["project_id"].astext == project_id)

            if filters.get("suite_id"):
                suite_id = InputValidator.validate_string(
                    str(filters["suite_id"]),
                    "suite_id",
                    max_length=100,
                )
                query = query.filter(Artifact.meta["suite_id"].astext == suite_id)

            if filters.get("status"):
                statuses = InputValidator.validate_list_of_strings(
                    filters["status"],
                    "status",
                    max_items=20,
                    max_item_length=50,
                )
                query = query.filter(Artifact.meta["status"].astext.in_(statuses))

            if filters.get("type"):
                test_types = InputValidator.validate_list_of_strings(
                    filters["type"],
                    "type",
                    max_items=20,
                    max_item_length=100,
                )
                query = query.filter(Artifact.meta["type"].astext.in_(test_types))

            if filters.get("priority"):
                priorities = InputValidator.validate_list_of_strings(
                    filters["priority"],
                    "priority",
                    max_items=10,
                    max_item_length=50,
                )
                query = query.filter(Artifact.meta["priority"].astext.in_(priorities))

            if filters.get("date_from"):
                date_from = InputValidator.validate_date(filters["date_from"], "date_from")
                query = query.filter(Artifact.created_at >= date_from)

            if filters.get("date_to"):
                date_to = InputValidator.validate_date(filters["date_to"], "date_to")
                query = query.filter(Artifact.created_at <= date_to)
        except ValueError as exc:
            context.add_error(f"Invalid filter in TestRailSource: {str(exc)}")
            return []

        artifacts = query.all()
        context.set_node_output(node["id"], artifacts)

        return artifacts
