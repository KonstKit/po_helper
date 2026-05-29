"""
Traceability Rules / Flow Builder API
======================================

This module provides the backend API for the Visual Flow Builder feature.
TraceabilityRule entities ARE flows - the flow_json field stores React Flow
graph data (nodes and edges) that define traceability automation rules.

API Endpoints (Flow Builder):
-----------------------------
- POST   /rules/validate     - Validate flow JSON without saving
- GET    /rules              - List all flows (with filtering)
- POST   /rules              - Create a new flow
- GET    /rules/{id}         - Get flow by ID
- PUT    /rules/{id}         - Update an existing flow
- DELETE /rules/{id}         - Delete a flow
- POST   /rules/{id}/execute - Execute flow and create traceability links

Schedule Management:
--------------------
- GET    /rules/{id}/schedule        - Get schedule settings
- PUT    /rules/{id}/schedule        - Update cron schedule

Webhook Triggers:
-----------------
- GET    /rules/{id}/webhook         - Get webhook configuration
- POST   /rules/{id}/webhook/enable  - Enable webhook and get token
- POST   /rules/{id}/webhook/disable - Disable webhook trigger
- POST   /webhook/{token}            - Execute via webhook (no auth)

Execution History:
------------------
- GET    /rules/executions           - All execution history
- GET    /rules/{id}/executions      - Execution history for one flow

Flow JSON Schema:
-----------------
The flow_json field contains React Flow data structure:
{
    "nodes": [
        {
            "id": "node-1",
            "type": "commitSource",       // Node type from SOURCE/PROCESSOR/ACTION
            "position": {"x": 100, "y": 50},
            "data": {
                "label": "Git Commits",
                "config": {...},          // Node-specific configuration
                "filters": {...}          // Source node filters
            }
        }
    ],
    "edges": [
        {
            "id": "edge-1",
            "source": "node-1",
            "target": "node-2",
            "sourceHandle": "output",
            "targetHandle": "input"
        }
    ]
}

Node Types:
-----------
SOURCE_NODE_TYPES:
  - commitSource     : Git commits with branch/author/date filters
  - jiraIssueSource  : Jira issues with project/status filters
  - confluenceSource : Confluence pages with space/label filters
  - testrailSource   : TestRail tests with project/status filters
  - manualSource     : Manually defined artifact collections

PROCESSOR_NODE_TYPES:
  - jiraKeyExtractor : Extract Jira keys from text (commit messages, etc.)
  - filterNode       : Filter artifacts by field/operator/value
  - transformNode    : Transform artifact data (placeholder)
  - decisionNode     : Conditional branching based on artifact count

ACTION_NODE_TYPES:
  - createLinkAction : Create traceability links between artifacts
  - queueReviewAction: Queue artifacts for manual review (placeholder)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.models import User, Permissions, Project
from app.models.traceability_rule import TraceabilityRule, TraceabilityRuleExecution
from app.schemas.traceability_rule import (
    TraceabilityRuleCreate,
    TraceabilityRuleUpdate,
    TraceabilityRuleResponse,
    TraceabilityRuleListResponse,
    TraceabilityRuleExecutionResponse,
    TraceabilityRuleExecutionListResponse,
    FlowValidationRequest,
    ValidationResult,
    ValidationError as ValidationErrorSchema,
    ValidationWarning as ValidationWarningSchema,
    FlowJSON,
    RuleScheduleUpdate,
    RuleScheduleResponse,
    RuleWebhookResponse,
)
from app.api.deps import ensure_project_access, require_permission
from app.core.config import settings
from app.services.audit_log import record_audit_event, record_audit_event_sync
from app.services.traceability.engine.nodes.transform_node import (
    SUPPORTED_TRANSFORM_TYPES,
    is_supported_transform_type,
)
from app.utils import (
    transactional_session,
    handle_api_error,
    count_with_filters,
    paginate_query,
    get_or_404,
)

router = APIRouter()


# =============================================================================
# Flow Validation Logic (mirrors frontend ruleValidation.ts)
# =============================================================================

# Node type classifications
SOURCE_NODE_TYPES = {
    "commitSource",
    "jiraIssueSource",
    "confluenceSource",
    "testrailSource",
    "manualSource",
}
ACTION_NODE_TYPES = {"createLinkAction", "queueReviewAction"}
PROCESSOR_NODE_TYPES = {"jiraKeyExtractor", "filterNode", "transformNode", "decisionNode"}


def validate_flow(flow_json: FlowJSON) -> ValidationResult:
    """
    Server-side validation of a traceability rule flow.
    Mirrors frontend ruleValidation.ts for consistency.
    """
    errors: list[ValidationErrorSchema] = []
    warnings: list[ValidationWarningSchema] = []
    nodes = flow_json.nodes
    edges = flow_json.edges

    # Rule 1: Must have at least one source node
    source_nodes = [n for n in nodes if n.type in SOURCE_NODE_TYPES]
    if not source_nodes:
        errors.append(
            ValidationErrorSchema(
                message="Rule must have at least one Source node (Commit, Jira Issue, Confluence, TestRail, or Manual)"
            )
        )

    # Rule 2: Must have at least one action node
    action_nodes = [n for n in nodes if n.type in ACTION_NODE_TYPES]
    if not action_nodes:
        errors.append(
            ValidationErrorSchema(
                message="Rule must have at least one Action node (Create Link, Queue Review, etc.)"
            )
        )

    # Rule 3: Check for disconnected nodes
    connected_node_ids = set()
    for edge in edges:
        connected_node_ids.add(edge.source)
        connected_node_ids.add(edge.target)

    for node in nodes:
        if node.id not in connected_node_ids and len(nodes) > 1:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Node "{label}" is not connected to any other nodes', node_id=node.id
                )
            )

    # Rule 4: Check for circular dependencies
    cycle = _detect_cycles(nodes, edges)
    if cycle:
        errors.append(
            ValidationErrorSchema(message=f"Circular dependency detected: {' → '.join(cycle)}")
        )

    # Rule 5: Validate source nodes have outputs
    for node in source_nodes:
        has_outgoing = any(e.source == node.id for e in edges)
        if not has_outgoing:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Source node "{label}" has no outgoing connections', node_id=node.id
                )
            )

    # Rule 6: Validate action nodes have inputs
    for node in action_nodes:
        has_incoming = any(e.target == node.id for e in edges)
        if not has_incoming:
            label = node.data.get("label", node.id)
            warnings.append(
                ValidationWarningSchema(
                    message=f'Action node "{label}" has no incoming connections', node_id=node.id
                )
            )

    # Rule 7: Validate processor nodes have both inputs and outputs
    processor_nodes = [n for n in nodes if n.type in PROCESSOR_NODE_TYPES]
    for node in processor_nodes:
        has_incoming = any(e.target == node.id for e in edges)
        has_outgoing = any(e.source == node.id for e in edges)
        label = node.data.get("label", node.id)

        if not has_incoming:
            warnings.append(
                ValidationWarningSchema(
                    message=f'Processor node "{label}" has no input', node_id=node.id
                )
            )
        if not has_outgoing:
            warnings.append(
                ValidationWarningSchema(
                    message=f'Processor node "{label}" has no output', node_id=node.id
                )
            )

    # Rule 8: Validate node-specific configurations
    for node in nodes:
        node_errors, node_warnings = _validate_node_configuration(node)
        errors.extend(node_errors)
        warnings.extend(node_warnings)

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


def _detect_cycles(nodes, edges) -> list[str]:
    """Detect circular dependencies using DFS."""
    adjacency_list: dict[str, list[str]] = {n.id: [] for n in nodes}
    for edge in edges:
        if edge.source in adjacency_list:
            adjacency_list[edge.source].append(edge.target)

    visited = set()
    recursion_stack = set()
    cycle = []

    def dfs(node_id: str, path: list[str]) -> bool:
        nonlocal cycle
        visited.add(node_id)
        recursion_stack.add(node_id)
        path.append(node_id)

        for neighbor in adjacency_list.get(node_id, []):
            if neighbor not in visited:
                if dfs(neighbor, path):
                    return True
            elif neighbor in recursion_stack:
                # Cycle detected
                cycle_start_idx = path.index(neighbor)
                cycle = path[cycle_start_idx:]
                cycle.append(neighbor)
                return True

        recursion_stack.discard(node_id)
        path.pop()
        return False

    for node in nodes:
        if node.id not in visited:
            if dfs(node.id, []):
                # Convert node IDs to labels
                node_map = {n.id: n.data.get("label", n.id) for n in nodes}
                return [node_map.get(nid, nid) for nid in cycle]

    return []


def _validate_node_configuration(
    node,
) -> tuple[list[ValidationErrorSchema], list[ValidationWarningSchema]]:
    """Validate individual node configuration.

    Returns (errors, warnings). Most checks emit only errors; the transform
    contract emits a warning when ``TRACEABILITY_TRANSFORM_STRICT`` is off
    so legacy rules stay editable/executable during a rolling deploy that
    has not yet applied Alembic revision 034.
    """
    errors: list[ValidationErrorSchema] = []
    warnings: list[ValidationWarningSchema] = []
    node_type = node.type
    config = node.data.get("config", {})
    label = node.data.get("label", node.id)

    if node_type == "jiraKeyExtractor":
        search_in = config.get("search_in", [])
        if not search_in or (isinstance(search_in, list) and len(search_in) == 0):
            errors.append(
                ValidationErrorSchema(
                    message=f'Jira Key Extractor "{label}" must have at least one search field selected',
                    node_id=node.id,
                )
            )
        if not config.get("pattern"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Jira Key Extractor "{label}" must have a regex pattern',
                    node_id=node.id,
                )
            )

    elif node_type == "createLinkAction":
        if not config.get("link_type"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Create Link action "{label}" must have a link type', node_id=node.id
                )
            )
        if config.get("bidirectional") and not config.get("reverse_link_type"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Create Link action "{label}" with bidirectional enabled must specify reverse link type',
                    node_id=node.id,
                )
            )

    elif node_type == "filterNode":
        if not config.get("field"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Filter node "{label}" must specify a field to filter on',
                    node_id=node.id,
                )
            )
        if not config.get("operator"):
            errors.append(
                ValidationErrorSchema(
                    message=f'Filter node "{label}" must specify an operator', node_id=node.id
                )
            )

    elif node_type == "transformNode":
        # transform_type is optional in the payload; absence implies the default
        # (passthrough). Only an explicit value outside the whitelist is rejected.
        # Strict mode mirrors runtime behavior: when the flag is off, legacy
        # values become a warning instead of a 400, so rules stored before
        # migration 034 stay editable/executable during the rollout window.
        if "transform_type" in config:
            transform_type = config.get("transform_type")
            if not is_supported_transform_type(transform_type):
                supported = ", ".join(sorted(SUPPORTED_TRANSFORM_TYPES))
                message = (
                    f'Transform node "{label}" has unsupported transform_type '
                    f'"{transform_type}"; supported values: {supported}'
                )
                if settings.TRACEABILITY_TRANSFORM_STRICT:
                    errors.append(
                        ValidationErrorSchema(message=message, node_id=node.id)
                    )
                else:
                    warnings.append(
                        ValidationWarningSchema(
                            message=f"{message} (strict mode disabled, will pass through)",
                            node_id=node.id,
                        )
                    )

    elif node_type == "decisionNode":
        condition_type = config.get("condition_type", "count_threshold")
        supported_condition_types = {
            "confidence_threshold",
            "count_threshold",
            "count_equals",
            "has_artifacts",
            "is_empty",
        }
        if condition_type not in supported_condition_types:
            errors.append(
                ValidationErrorSchema(
                    message=(
                        f'Decision node "{label}" has unsupported condition_type '
                        f'"{condition_type}"'
                    ),
                    node_id=node.id,
                )
            )

        if condition_type == "confidence_threshold":
            threshold = config.get("threshold")
            if threshold is None:
                errors.append(
                    ValidationErrorSchema(
                        message=(
                            f'Decision node "{label}" with confidence_threshold '
                            "must provide a threshold"
                        ),
                        node_id=node.id,
                    )
                )
            else:
                try:
                    threshold_value = float(threshold)
                except (TypeError, ValueError):
                    errors.append(
                        ValidationErrorSchema(
                            message=(
                                f'Decision node "{label}" confidence threshold '
                                "must be numeric"
                            ),
                            node_id=node.id,
                        )
                    )
                else:
                    if not 0 <= threshold_value <= 100:
                        errors.append(
                            ValidationErrorSchema(
                                message=(
                                    f'Decision node "{label}" confidence threshold must '
                                    "be between 0 and 100"
                                ),
                                node_id=node.id,
                            )
                        )

    return errors, warnings


def _build_flow_validation_detail(
    validation_result: ValidationResult,
    *,
    code: str = "flow_validation_failed",
    message: str = "Flow validation failed",
) -> dict:
    return {
        "code": code,
        "message": message,
        "errors": [error.model_dump() for error in validation_result.errors],
        "warnings": [warning.model_dump() for warning in validation_result.warnings],
    }


def _ensure_flow_valid_or_400(flow_json: FlowJSON) -> ValidationResult:
    validation_result = validate_flow(flow_json)
    if not validation_result.valid:
        raise HTTPException(
            status_code=400,
            detail=_build_flow_validation_detail(validation_result),
        )
    return validation_result


def _normalize_unsupported_transform_types(flow_json: FlowJSON) -> bool:
    """Rewrite unsupported transform_type to passthrough in non-strict mode.

    Without this, a rule saved during the rollout window
    (TRACEABILITY_TRANSFORM_STRICT=False) would persist its unsupported
    value as-is and start failing as soon as strict mode is turned back
    on. Alembic revision 034 only rewrites rows that already existed, so
    save-time normalization is needed for new/updated rules. Mutates
    `flow_json.nodes` in place; no-op when strict mode is enabled.

    Returns True if any node was rewritten, so callers (notably the
    partial-update endpoint) can decide whether the normalized flow
    needs to be persisted back to the database even when the client
    only sent metadata fields.
    """
    if settings.TRACEABILITY_TRANSFORM_STRICT:
        return False
    rewritten = False
    audit_timestamp = datetime.now(timezone.utc).isoformat()
    for node in flow_json.nodes:
        if node.type != "transformNode":
            continue
        data = node.data or {}
        config = data.get("config") if isinstance(data, dict) else None
        if not isinstance(config, dict) or "transform_type" not in config:
            continue
        value = config.get("transform_type")
        if is_supported_transform_type(value):
            continue
        config["transform_type"] = "passthrough"
        audit = config.setdefault("_legacy_transform_type_audit", {})
        audit["previous_value"] = value
        audit["rewritten_at"] = audit_timestamp
        audit["rewritten_by"] = (
            "api_v1/endpoints/traceability/rules.py:_normalize_unsupported_transform_types"
        )
        rewritten = True
    return rewritten


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/rules/validate", response_model=ValidationResult)
async def validate_rule_flow(
    request: FlowValidationRequest,
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
) -> ValidationResult:
    """
    Validate a traceability rule flow JSON without saving.

    Returns validation result matching frontend ruleValidation.ts format.
    Use this endpoint before saving or executing a rule to ensure it's valid.
    """
    return validate_flow(request.flow_json)


@router.get("/rules", response_model=TraceabilityRuleListResponse)
async def list_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    enabled: Optional[bool] = None,
    category: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """List all traceability rules with optional filters."""
    query = select(TraceabilityRule)
    filters = []
    if enabled is not None:
        filters.append(TraceabilityRule.enabled == enabled)
    if category:
        filters.append(TraceabilityRule.category == category)
    if project_id:
        filters.append(TraceabilityRule.project_id == project_id)
        await ensure_project_access(project_id, db, current_user)

    if filters:
        query = query.where(and_(*filters))

    total = await count_with_filters(db, TraceabilityRule, filters)

    query = query.order_by(TraceabilityRule.created_at.desc())
    rules = await paginate_query(db, query, skip, limit)

    return TraceabilityRuleListResponse(
        total=total, items=[TraceabilityRuleResponse.from_db(rule) for rule in rules]
    )


# NOTE: This route MUST be defined BEFORE /rules/{rule_id} to avoid FastAPI matching "executions" as rule_id
@router.get("/rules/executions")
async def get_all_rule_executions(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    rule_id: Optional[int] = Query(None, description="Filter by rule id"),
    status: Optional[str] = Query(None, description="Filter by status: success, failed"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get all traceability rule executions with pagination and filtering."""
    query = select(TraceabilityRuleExecution).order_by(TraceabilityRuleExecution.started_at.desc())
    filters = []

    if rule_id is not None:
        query = query.where(TraceabilityRuleExecution.rule_id == rule_id)
        filters.append(TraceabilityRuleExecution.rule_id == rule_id)

    if status:
        query = query.where(TraceabilityRuleExecution.status == status)
        filters.append(TraceabilityRuleExecution.status == status)

    total = await count_with_filters(db, TraceabilityRuleExecution, filters or None)

    executions = await paginate_query(db, query, skip, limit)

    items = []
    for execution in executions:
        rule_result = await db.execute(
            select(TraceabilityRule).where(TraceabilityRule.id == execution.rule_id)
        )
        rule = rule_result.scalar_one_or_none()

        error_details = execution.error_details or {}
        exec_data = {
            "id": execution.id,
            "rule_id": execution.rule_id,
            "rule_name": rule.name if rule else f"Rule #{execution.rule_id}",
            "status": execution.status,
            "links_created": execution.links_created or 0,
            "links_updated": execution.links_updated or 0,
            "artifacts_processed": execution.artifacts_processed or 0,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
            "error_message": execution.error_message,
            "error_details": execution.error_details,
            "rolled_back": bool(error_details.get("atomic_rollback", False))
            if isinstance(error_details, dict)
            else False,
            "executed_at": execution.started_at.isoformat() if execution.started_at else None,
            "execution_log": {
                "errors": error_details.get("errors", [])
                if isinstance(error_details, dict)
                else [],
                "warnings": error_details.get("warnings", [])
                if isinstance(error_details, dict)
                else [],
                "links_created": execution.links_created or 0,
                "links_updated": execution.links_updated or 0,
                "artifacts_processed": execution.artifacts_processed or 0,
                "rolled_back": bool(error_details.get("atomic_rollback", False))
                if isinstance(error_details, dict)
                else False,
            },
        }
        items.append(exec_data)

    return {"total": total, "items": items}


@router.get("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get a specific traceability rule by ID."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)
    return TraceabilityRuleResponse.from_db(rule)


@router.post("/rules", response_model=TraceabilityRuleResponse, status_code=201)
async def create_rule(
    rule_data: TraceabilityRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Create a new traceability rule."""
    _normalize_unsupported_transform_types(rule_data.flow_json)
    _ensure_flow_valid_or_400(rule_data.flow_json)

    existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400, detail=f"Rule with name '{rule_data.name}' already exists"
        )

    if rule_data.project_id is not None:
        await ensure_project_access(rule_data.project_id, db, current_user)

    next_scheduled_run = None
    if rule_data.schedule_enabled and rule_data.schedule_cron:
        if not _validate_cron_expression(rule_data.schedule_cron):
            raise HTTPException(
                status_code=400,
                detail="Invalid cron expression. Expected format: 'minute hour day month weekday'",
            )
        next_scheduled_run = _calculate_next_run(rule_data.schedule_cron)

    new_rule = TraceabilityRule(
        name=rule_data.name,
        description=rule_data.description,
        flow_json=rule_data.flow_json.model_dump(),
        enabled=rule_data.enabled,
        category=rule_data.category,
        tags=rule_data.tags,
        project_id=rule_data.project_id,
        created_by_id=current_user.id,
        schedule_cron=rule_data.schedule_cron,
        schedule_enabled=rule_data.schedule_enabled,
        trigger_on_webhook=rule_data.trigger_on_webhook,
        execute_on_sync_complete=rule_data.execute_on_sync_complete,
        next_scheduled_run=next_scheduled_run,
    )

    async with transactional_session(db):
        db.add(new_rule)
        await db.flush()
        await record_audit_event(
            db,
            action="create",
            entity_type="traceability_rule",
            entity_id=new_rule.id,
            actor_id=current_user.id,
            project_id=new_rule.project_id,
            payload={
                "name": new_rule.name,
                "enabled": new_rule.enabled,
                "category": new_rule.category,
                "tags": new_rule.tags,
            },
        )
    await db.refresh(new_rule)

    return TraceabilityRuleResponse.from_db(new_rule)


@router.put("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: TraceabilityRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Update an existing traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    if rule_data.name and rule_data.name != rule.name:
        existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail=f"Rule with name '{rule_data.name}' already exists"
            )

    if rule_data.flow_json is not None:
        flow_for_validation = rule_data.flow_json
    else:
        try:
            flow_for_validation = FlowJSON.model_validate(rule.flow_json)
        except PydanticValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "flow_schema_invalid",
                    "message": "Stored flow_json schema is invalid",
                    "errors": [{"type": "error", "message": str(exc), "node_id": None, "edge_id": None}],
                    "warnings": [],
                },
            ) from exc

    normalized_in_place = _normalize_unsupported_transform_types(flow_for_validation)
    _ensure_flow_valid_or_400(flow_for_validation)

    update_data = rule_data.model_dump(exclude_unset=True)

    # Partial update path: client did not send flow_json but normalization
    # rewrote stored legacy values. Persist the rewrite so a later strict
    # mode flip does not break this rule (the alembic 034 backfill cannot
    # catch rows that bypass it via metadata-only updates).
    if normalized_in_place and rule_data.flow_json is None:
        update_data["flow_json"] = flow_for_validation.model_dump()

    if "schedule_cron" in update_data and update_data["schedule_cron"]:
        if not _validate_cron_expression(update_data["schedule_cron"]):
            raise HTTPException(
                status_code=400,
                detail="Invalid cron expression. Expected format: 'minute hour day month weekday'",
            )

    if "schedule_cron" in update_data:
        schedule_cron = update_data["schedule_cron"]
        if schedule_cron:
            update_data["next_scheduled_run"] = _calculate_next_run(schedule_cron)
        else:
            update_data["next_scheduled_run"] = None

    if "schedule_enabled" in update_data:
        schedule_enabled = bool(update_data["schedule_enabled"])
        if not schedule_enabled:
            update_data["next_scheduled_run"] = None
        else:
            effective_cron = update_data.get("schedule_cron", rule.schedule_cron)
            if effective_cron:
                update_data["next_scheduled_run"] = _calculate_next_run(effective_cron)

    changed_fields = sorted(update_data.keys())

    async with transactional_session(db):
        for field, value in update_data.items():
            setattr(rule, field, value)
        if changed_fields:
            await record_audit_event(
                db,
                action="update",
                entity_type="traceability_rule",
                entity_id=rule.id,
                actor_id=current_user.id,
                project_id=rule.project_id,
                payload={"fields": changed_fields},
            )
    await db.refresh(rule)

    return TraceabilityRuleResponse.from_db(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Delete a traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    # Delete-cascade contract (plan_73 step 1B):
    # - Unresolved (open) review items block deletion with 409.
    # - Terminal review items preserve history by clearing the rule reference
    #   (a rule-name snapshot is retained in metadata).
    # - Artifact links and suggested links are NOT deleted.
    # - Rule execution rows are removed via the existing ORM cascade.
    from app.models.traceability_review import (
        OPEN_REVIEW_STATUSES,
        TERMINAL_REVIEW_STATUSES,
        TraceabilityReviewItem,
    )

    open_count = await count_with_filters(
        db,
        TraceabilityReviewItem,
        [
            TraceabilityReviewItem.rule_id == rule_id,
            TraceabilityReviewItem.status.in_(OPEN_REVIEW_STATUSES),
        ],
    )
    if open_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete rule {rule_id}: {open_count} unresolved review "
                f"item(s) reference it. Resolve or reject them first."
            ),
        )

    # Detach only terminal items (the open-count guard above already 409s if
    # any open item exists). Filtering on status keeps a review item that is
    # created/reopened concurrently — after the guard ran — from being silently
    # detached here instead of blocking the delete.
    terminal_items = (
        await db.execute(
            select(TraceabilityReviewItem).where(
                TraceabilityReviewItem.rule_id == rule_id,
                TraceabilityReviewItem.status.in_(TERMINAL_REVIEW_STATUSES),
            )
        )
    ).scalars().all()

    rule_name = rule.name
    async with transactional_session(db):
        for item in terminal_items:
            snapshot = dict(item.meta or {})
            snapshot["deleted_rule"] = {"id": rule_id, "name": rule_name}
            item.meta = snapshot
            item.rule_id = None
        await record_audit_event(
            db,
            action="delete",
            entity_type="traceability_rule",
            entity_id=rule.id,
            actor_id=current_user.id,
            project_id=rule.project_id,
            payload={"name": rule_name, "review_items_detached": len(terminal_items)},
        )
        await db.delete(rule)


@router.get("/rules/{rule_id}/executions", response_model=TraceabilityRuleExecutionListResponse)
async def list_rule_executions(
    rule_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """List execution history for a specific rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    filters = [TraceabilityRuleExecution.rule_id == rule_id]
    total = await count_with_filters(db, TraceabilityRuleExecution, filters)

    query = (
        select(TraceabilityRuleExecution)
        .where(TraceabilityRuleExecution.rule_id == rule_id)
        .order_by(TraceabilityRuleExecution.started_at.desc())
    )
    executions = await paginate_query(db, query, skip, limit)

    return TraceabilityRuleExecutionListResponse(
        total=total, items=[TraceabilityRuleExecutionResponse.from_db(ex) for ex in executions]
    )


@router.post("/rules/{rule_id}/execute", response_model=dict)
def execute_rule(
    rule_id: int,
    db: Session = Depends(get_sync_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Execute a traceability rule.

    Uses synchronous database session since rule execution engine
    performs complex graph traversal and link creation operations.
    """
    from app.services.rule_execution_engine import RuleExecutionEngine

    rule = (
        db.query(TraceabilityRule).filter(TraceabilityRule.id == rule_id).first()
    )
    if rule is None:
        raise HTTPException(status_code=404, detail=f"Rule with id {rule_id}")
    if rule.project_id is not None:
        project = db.query(Project).filter(Project.id == rule.project_id).first()
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if not current_user.is_active:
            raise HTTPException(status_code=403, detail="Inactive user")

    try:
        flow_json = FlowJSON.model_validate(rule.flow_json)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "flow_schema_invalid",
                "message": "Stored flow_json schema is invalid",
                "errors": [{"type": "error", "message": str(exc), "node_id": None, "edge_id": None}],
                "warnings": [],
            },
        ) from exc

    _ensure_flow_valid_or_400(flow_json)

    engine = RuleExecutionEngine(db)

    with handle_api_error(
        operation="execute_rule",
        status_code=500,
        context={"rule_id": rule_id},
        exception_map={ValueError: 400},
    ):
        result = engine.execute_rule(rule_id)
        record_audit_event_sync(
            db,
            action="execute",
            entity_type="traceability_rule",
            entity_id=rule_id,
            actor_id=current_user.id,
            project_id=rule.project_id,
            outcome=str(result.get("status", "success")),
            payload={
                "execution_id": result.get("execution_id"),
                "links_created": result.get("links_created"),
            },
        )
        return result


# =============================================================================
# Schedule Management Endpoints
# =============================================================================


def _calculate_next_run(cron_expression: str) -> Optional[datetime]:
    """Calculate next scheduled run from cron expression."""
    try:
        from croniter import croniter
        from datetime import datetime, timezone

        cron = croniter(cron_expression, datetime.now(timezone.utc))
        return cron.get_next(datetime)
    except Exception:
        # croniter not installed or invalid expression
        return None


def _validate_cron_expression(cron_expression: str) -> bool:
    """Validate a cron expression format."""
    try:
        from croniter import croniter

        croniter(cron_expression)
        return True
    except Exception:
        # Basic validation if croniter not available
        parts = cron_expression.strip().split()
        return len(parts) == 5


def _generate_webhook_token() -> str:
    """Generate a secure random token for webhook authentication."""
    import secrets

    return secrets.token_urlsafe(32)


@router.get("/rules/{rule_id}/schedule", response_model=RuleScheduleResponse)
async def get_rule_schedule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get schedule settings for a specific rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    return RuleScheduleResponse(
        rule_id=rule.id,
        schedule_cron=rule.schedule_cron,
        schedule_enabled=rule.schedule_enabled,
        next_scheduled_run=rule.next_scheduled_run,
    )


@router.put("/rules/{rule_id}/schedule", response_model=RuleScheduleResponse)
async def update_rule_schedule(
    rule_id: int,
    schedule_data: RuleScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Update schedule settings for a rule.

    Cron expression format: "minute hour day month weekday"
    Examples:
    - "0 */6 * * *" - Every 6 hours
    - "0 9 * * 1-5" - 9 AM on weekdays
    - "0 0 * * 0" - Midnight on Sundays
    """
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    # Validate cron expression if provided
    if schedule_data.schedule_cron is not None:
        if schedule_data.schedule_cron and not _validate_cron_expression(
            schedule_data.schedule_cron
        ):
            raise HTTPException(
                status_code=400,
                detail="Invalid cron expression. Expected format: 'minute hour day month weekday'",
            )

    async with transactional_session(db):
        if schedule_data.schedule_cron is not None:
            rule.schedule_cron = schedule_data.schedule_cron
            # Calculate next run if cron is set
            if schedule_data.schedule_cron:
                rule.next_scheduled_run = _calculate_next_run(schedule_data.schedule_cron)
            else:
                rule.next_scheduled_run = None

        if schedule_data.schedule_enabled is not None:
            rule.schedule_enabled = schedule_data.schedule_enabled
            # Disable also clears next run
            if not schedule_data.schedule_enabled:
                rule.next_scheduled_run = None
            elif rule.schedule_cron:
                rule.next_scheduled_run = _calculate_next_run(rule.schedule_cron)
        await record_audit_event(
            db,
            action="update_schedule",
            entity_type="traceability_rule",
            entity_id=rule.id,
            actor_id=current_user.id,
            project_id=rule.project_id,
            payload={
                "schedule_cron": rule.schedule_cron,
                "schedule_enabled": rule.schedule_enabled,
            },
        )

    await db.refresh(rule)

    return RuleScheduleResponse(
        rule_id=rule.id,
        schedule_cron=rule.schedule_cron,
        schedule_enabled=rule.schedule_enabled,
        next_scheduled_run=rule.next_scheduled_run,
    )


@router.get("/rules/{rule_id}/webhook", response_model=RuleWebhookResponse)
async def get_rule_webhook(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """Get webhook settings for a specific rule (token is hidden)."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    webhook_url = None
    if rule.trigger_on_webhook and rule.webhook_token:
        # Build webhook URL - this would be configurable in production
        webhook_url = f"/api/v1/traceability/webhook/{rule.webhook_token}"

    return RuleWebhookResponse(
        rule_id=rule.id,
        trigger_on_webhook=rule.trigger_on_webhook,
        webhook_token=None,  # Never expose existing token
        webhook_url=webhook_url,
    )


@router.post("/rules/{rule_id}/webhook/enable", response_model=RuleWebhookResponse)
async def enable_rule_webhook(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """
    Enable webhook triggering for a rule and generate a new token.

    WARNING: This generates a new token. The token is only shown once in this response.
    Store it securely - it cannot be retrieved again.
    """
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    new_token = _generate_webhook_token()

    async with transactional_session(db):
        rule.trigger_on_webhook = True
        rule.webhook_token = new_token
        await record_audit_event(
            db,
            action="enable_webhook",
            entity_type="traceability_rule",
            entity_id=rule.id,
            actor_id=current_user.id,
            project_id=rule.project_id,
            payload={"trigger_on_webhook": True},
        )

    await db.refresh(rule)

    webhook_url = f"/api/v1/traceability/webhook/{new_token}"

    return RuleWebhookResponse(
        rule_id=rule.id,
        trigger_on_webhook=True,
        webhook_token=new_token,  # Only shown once on generation
        webhook_url=webhook_url,
    )


@router.post("/rules/{rule_id}/webhook/disable", response_model=RuleWebhookResponse)
async def disable_rule_webhook(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_MANAGE)),
):
    """Disable webhook triggering for a rule and clear the token."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    if rule.project_id is not None:
        await ensure_project_access(rule.project_id, db, current_user)

    async with transactional_session(db):
        rule.trigger_on_webhook = False
        rule.webhook_token = None
        await record_audit_event(
            db,
            action="disable_webhook",
            entity_type="traceability_rule",
            entity_id=rule.id,
            actor_id=current_user.id,
            project_id=rule.project_id,
            payload={"trigger_on_webhook": False},
        )

    await db.refresh(rule)

    return RuleWebhookResponse(
        rule_id=rule.id, trigger_on_webhook=False, webhook_token=None, webhook_url=None
    )


# =============================================================================
# Webhook Execution Endpoint (no auth - uses token)
# =============================================================================


@router.post("/webhook/{webhook_token}")
def execute_rule_by_webhook(
    webhook_token: str,
    db: Session = Depends(get_sync_db),
):
    """
    Execute a rule via webhook token.

    This endpoint is unauthenticated - the webhook_token itself provides authorization.
    The token must match a rule with trigger_on_webhook=True.
    """
    from app.services.rule_execution_engine import RuleExecutionEngine

    # Find rule by webhook token
    rule = (
        db.query(TraceabilityRule)
        .filter(
            TraceabilityRule.webhook_token == webhook_token,
            TraceabilityRule.trigger_on_webhook,
        )
        .first()
    )

    if not rule:
        raise HTTPException(status_code=404, detail="Invalid webhook token or webhook not enabled")

    if not rule.enabled:
        raise HTTPException(status_code=400, detail="Rule is disabled")

    try:
        flow_json = FlowJSON.model_validate(rule.flow_json)
    except PydanticValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "flow_schema_invalid",
                "message": "Stored flow_json schema is invalid",
                "errors": [{"type": "error", "message": str(exc), "node_id": None, "edge_id": None}],
                "warnings": [],
            },
        ) from exc

    _ensure_flow_valid_or_400(flow_json)

    engine = RuleExecutionEngine(db)

    with handle_api_error(
        operation="execute_rule_webhook",
        status_code=500,
        context={"rule_id": rule.id},
        exception_map={ValueError: 400},
    ):
        result = engine.execute_rule(rule.id)
        record_audit_event_sync(
            db,
            action="execute_webhook",
            entity_type="traceability_rule",
            entity_id=rule.id,
            project_id=rule.project_id,
            outcome=str(result.get("status", "success")),
            payload={
                "execution_id": result.get("execution_id"),
                "links_created": result.get("links_created"),
            },
        )
        return {"rule_id": rule.id, "rule_name": rule.name, **result}
