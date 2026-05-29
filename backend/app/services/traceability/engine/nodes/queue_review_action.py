from __future__ import annotations

from typing import Any, Dict, List

from app.models.traceability import Artifact
from app.models.traceability_review import REVIEW_PRIORITIES
from app.services.traceability.engine.context import ExecutionContext
from app.services.traceability.engine.nodes.base import NodeExecutor

# Priorities accepted by the review queue. Single source of truth is the
# TraceabilityReviewItem model, so the set cannot drift from the DB/API.
_ALLOWED_PRIORITIES = set(REVIEW_PRIORITIES)


class QueueReviewActionExecutor(NodeExecutor):
    """Action Node: Queue artifacts for durable manual review.

    Each input artifact is registered as a review *candidate* on the execution
    context. The engine persists these as ``TraceabilityReviewItem`` rows after
    the execution record is created, applying deduplication so a rerun does not
    pile up duplicate open items for the same (project, artifact, rule, node).
    See plan_70.
    """

    def execute(self, node: Dict[str, Any], context: ExecutionContext) -> List[Artifact]:
        data = node.get("data", {})
        config = data.get("config", {})

        input_artifacts = context.get_input_artifacts(node["id"])

        if not input_artifacts:
            context.add_warning(f"QueueReviewAction {node['id']} received no artifacts to review")
            context.set_node_output(node["id"], [])
            return []

        review_reason = config.get("reason", "Manual review requested by traceability rule")
        priority = config.get("priority", "normal")
        if priority not in _ALLOWED_PRIORITIES:
            context.add_warning(
                f"QueueReviewAction {node['id']} got unknown priority '{priority}', "
                f"defaulting to 'normal'"
            )
            priority = "normal"

        queued = 0
        for artifact in input_artifacts:
            artifact_id = getattr(artifact, "id", None)
            # bool is a subclass of int — reject it so a stray boolean id is not
            # coerced into a persistent artifact_id 0/1.
            if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
                # Unsaved/synthetic artifact cannot be referenced durably.
                context.add_warning(
                    f"QueueReviewAction {node['id']} skipped an artifact without a "
                    f"persistent id ({artifact.type} '{artifact.external_id}')"
                )
                continue

            context.add_review_candidate(
                {
                    "artifact_id": artifact_id,
                    "project_id": getattr(artifact, "project_id", None),
                    "tenant_id": getattr(artifact, "tenant_id", None),
                    "node_id": node["id"],
                    "priority": priority,
                    "reason": review_reason,
                    "meta": {
                        "artifact_type": artifact.type,
                        "external_id": artifact.external_id,
                        "title": artifact.title,
                        "node_label": data.get("label"),
                    },
                }
            )
            queued += 1

        if queued:
            context.add_warning(
                f"Queued {queued} artifact(s) for manual review "
                f"(priority: {priority}, reason: {review_reason})"
            )

        context.set_node_output(node["id"], [])
        return []
