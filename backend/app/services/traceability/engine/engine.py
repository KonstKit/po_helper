from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.registry import ExecutorRegistry
from app.services.traceability.engine.nodes.commit_source import CommitSourceExecutor
from app.services.traceability.engine.nodes.jira_issue_source import JiraIssueSourceExecutor
from app.services.traceability.engine.nodes.confluence_source import ConfluenceSourceExecutor
from app.services.traceability.engine.nodes.testrail_source import TestRailSourceExecutor
from app.services.traceability.engine.nodes.manual_source import ManualArtifactSourceExecutor
from app.services.traceability.engine.nodes.jira_key_extractor import JiraKeyExtractorExecutor
from app.services.traceability.engine.nodes.filter_node import FilterNodeExecutor
from app.services.traceability.engine.nodes.transform_node import TransformNodeExecutor
from app.services.traceability.engine.nodes.decision_node import DecisionNodeExecutor
from app.services.traceability.engine.nodes.create_link_action import CreateLinkActionExecutor
from app.services.traceability.engine.nodes.queue_review_action import QueueReviewActionExecutor


def build_default_registry() -> ExecutorRegistry:
    registry = ExecutorRegistry()
    registry.register("commitSource", CommitSourceExecutor())
    registry.register("jiraIssueSource", JiraIssueSourceExecutor())
    registry.register("confluenceSource", ConfluenceSourceExecutor())
    registry.register("testrailSource", TestRailSourceExecutor())
    registry.register("manualSource", ManualArtifactSourceExecutor())
    registry.register("jiraKeyExtractor", JiraKeyExtractorExecutor())
    registry.register("filterNode", FilterNodeExecutor())
    registry.register("transformNode", TransformNodeExecutor())
    registry.register("decisionNode", DecisionNodeExecutor())
    registry.register("createLinkAction", CreateLinkActionExecutor())
    registry.register("queueReviewAction", QueueReviewActionExecutor())
    return registry


class RuleExecutionEngine:
    """Движок выполнения правил трассировки."""

    def __init__(self, db: Session, registry: Optional[ExecutorRegistry] = None):
        self.db = db
        self.registry = registry or build_default_registry()

    def execute_rule(self, rule_id: int) -> Dict[str, Any]:
        """Выполнить правило трассировки."""

        rule = self.db.query(TraceabilityRule).filter(TraceabilityRule.id == rule_id).first()
        if not rule:
            raise ValueError(f"Rule {rule_id} not found")

        if not rule.enabled:
            raise ValueError(f"Rule {rule_id} is disabled")

        raw_flow: Any = rule.flow_json
        if isinstance(raw_flow, str):
            flow_json = json.loads(raw_flow)
        elif isinstance(raw_flow, dict):
            flow_json = raw_flow
        else:
            flow_json = {}
        nodes = flow_json.get("nodes", [])
        edges = flow_json.get("edges", [])

        context = ExecutionContext(rule_id, self.db, edges)

        execution_order = self._topological_sort(nodes, edges)

        for node_id in execution_order:
            node = next((n for n in nodes if n["id"] == node_id), None)
            if not node:
                context.add_error(f"Node {node_id} not found")
                continue

            node_type = node.get("type")
            executor = self.registry.get(node_type)

            if not executor:
                context.add_error(f"No executor for node type: {node_type}")
                continue

            try:
                executor.execute(node, context)
            except Exception as exc:
                context.add_error(f"Error executing node {node_id}: {str(exc)}")

        execution = TraceabilityRuleExecution(
            rule_id=rule_id,
            status="success" if not context.errors else "failed",
            links_created=len(context.links_created),
            completed_at=datetime.utcnow(),
            error_message="; ".join(context.errors) if context.errors else None,
            error_details={
                "errors": context.errors,
                "warnings": context.warnings,
            }
            if context.errors or context.warnings
            else None,
        )
        self.db.add(execution)

        rule.total_executions += 1
        if not context.errors:
            rule.successful_executions += 1
        else:
            rule.failed_executions += 1
        rule.last_executed_at = datetime.utcnow()

        self.db.commit()

        return {
            "execution_id": execution.id,
            "status": execution.status,
            "links_created": len(context.links_created),
            "errors": context.errors,
            "warnings": context.warnings,
        }

    def _topological_sort(
        self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]
    ) -> List[str]:
        """Топологическая сортировка нод для определения порядка выполнения."""
        graph: Dict[str, List[str]] = {node["id"]: [] for node in nodes}
        in_degree = {node["id"]: 0 for node in nodes}

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            graph[source].append(target)
            in_degree[target] += 1

        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result: List[str] = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(nodes):
            raise ValueError("Cycle detected in rule graph")

        return result
