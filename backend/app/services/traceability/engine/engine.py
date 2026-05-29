from __future__ import annotations

import json
from datetime import datetime, timezone
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

    def execute_rule(self, rule_id: int, atomic: bool = True) -> Dict[str, Any]:
        """Выполнить правило трассировки.

        Args:
            rule_id: ID правила для выполнения
            atomic: Если True, откатывает все созданные связи при ошибках.
                   Если False, сохраняет частичные результаты (legacy behavior).

        Returns:
            Результат выполнения с execution_id, status, links_created, errors, warnings
        """
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

        # Determine final status
        has_errors = bool(context.errors)

        # Rollback created links if atomic mode and errors occurred
        if atomic and has_errors:
            self.db.rollback()
            links_created_count = 0
        else:
            links_created_count = len(context.links_created)

        links_updated_count = 0  # Reserved for future link update behavior.
        artifacts_processed_count = len(context.processed_artifact_ids)

        # Create execution record (after potential rollback, in a new mini-transaction)
        execution = TraceabilityRuleExecution(
            rule_id=rule_id,
            status="success" if not has_errors else "failed",
            links_created=links_created_count,
            links_updated=links_updated_count,
            artifacts_processed=artifacts_processed_count,
            completed_at=datetime.now(timezone.utc),
            error_message="; ".join(context.errors) if context.errors else None,
            error_details={
                "errors": context.errors,
                "warnings": context.warnings,
                "atomic_rollback": atomic and has_errors,
            }
            if context.errors or context.warnings
            else None,
        )
        self.db.add(execution)
        # Flush so the execution row gets an id we can attach to review items.
        self.db.flush()

        # Persist durable manual-review work items (plan_70). Candidates are
        # plain dicts collected during the run, so they survive the atomic
        # rollback above and are recorded alongside this execution.
        review_summary = {"created": 0, "updated": 0}
        if context.review_candidates:
            from app.services.traceability.review_service import (
                persist_review_candidates_sync,
            )

            review_summary = persist_review_candidates_sync(
                self.db,
                rule_id=rule_id,
                execution_id=execution.id,
                candidates=context.review_candidates,
            )

        rule.total_executions += 1
        if not has_errors:
            rule.successful_executions += 1
        else:
            rule.failed_executions += 1
        rule.last_executed_at = datetime.now(timezone.utc)

        self.db.commit()

        return {
            "execution_id": execution.id,
            "status": execution.status,
            "links_created": links_created_count,
            "links_updated": links_updated_count,
            "artifacts_processed": artifacts_processed_count,
            "review_items_created": review_summary["created"],
            "review_items_updated": review_summary["updated"],
            "errors": context.errors,
            "warnings": context.warnings,
            "rolled_back": atomic and has_errors,
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
