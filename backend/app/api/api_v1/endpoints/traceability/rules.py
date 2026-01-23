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

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.core.database import get_db, get_sync_db
from app.models import User
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
from app.api.deps import get_current_user
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
        node_errors = _validate_node_configuration(node)
        errors.extend(node_errors)

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


def _validate_node_configuration(node) -> list[ValidationErrorSchema]:
    """Validate individual node configuration."""
    errors = []
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

    return errors


# =============================================================================
# API Endpoints
# =============================================================================


@router.post("/rules/validate", response_model=ValidationResult)
async def validate_rule_flow(
    request: FlowValidationRequest,
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
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
    status: Optional[str] = Query(None, description="Filter by status: success, failed"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all traceability rule executions with pagination and filtering."""
    query = select(TraceabilityRuleExecution).order_by(TraceabilityRuleExecution.started_at.desc())

    if status:
        query = query.where(TraceabilityRuleExecution.status == status)

    filters = [TraceabilityRuleExecution.status == status] if status else None
    total = await count_with_filters(db, TraceabilityRuleExecution, filters)

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
            "executed_at": execution.started_at.isoformat() if execution.started_at else None,
            "execution_log": {
                "errors": error_details.get("errors", [])
                if isinstance(error_details, dict)
                else [],
                "warnings": error_details.get("warnings", [])
                if isinstance(error_details, dict)
                else [],
                "links_created": execution.links_created or 0,
            },
        }
        items.append(exec_data)

    return {"total": total, "items": items}


@router.get("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific traceability rule by ID."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )
    return TraceabilityRuleResponse.from_db(rule)


@router.post("/rules", response_model=TraceabilityRuleResponse, status_code=201)
async def create_rule(
    rule_data: TraceabilityRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new traceability rule."""
    existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
    existing_result = await db.execute(existing_query)
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=400, detail=f"Rule with name '{rule_data.name}' already exists"
        )

    new_rule = TraceabilityRule(
        name=rule_data.name,
        description=rule_data.description,
        flow_json=rule_data.flow_json.model_dump(),
        enabled=rule_data.enabled,
        category=rule_data.category,
        tags=rule_data.tags,
        project_id=rule_data.project_id,
        created_by_id=current_user.id,
    )

    async with transactional_session(db):
        db.add(new_rule)
    await db.refresh(new_rule)

    return TraceabilityRuleResponse.from_db(new_rule)


@router.put("/rules/{rule_id}", response_model=TraceabilityRuleResponse)
async def update_rule(
    rule_id: int,
    rule_data: TraceabilityRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

    if rule_data.name and rule_data.name != rule.name:
        existing_query = select(TraceabilityRule).where(TraceabilityRule.name == rule_data.name)
        existing_result = await db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            raise HTTPException(
                status_code=400, detail=f"Rule with name '{rule_data.name}' already exists"
            )

    update_data = rule_data.model_dump(exclude_unset=True)
    if "flow_json" in update_data and update_data["flow_json"]:
        update_data["flow_json"] = update_data["flow_json"]

    async with transactional_session(db):
        for field, value in update_data.items():
            setattr(rule, field, value)
    await db.refresh(rule)

    return TraceabilityRuleResponse.from_db(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a traceability rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

    async with transactional_session(db):
        await db.delete(rule)


@router.get("/rules/{rule_id}/executions", response_model=TraceabilityRuleExecutionListResponse)
async def list_rule_executions(
    rule_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List execution history for a specific rule."""
    await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

    filters = [TraceabilityRuleExecution.rule_id == rule_id]
    total = await count_with_filters(db, TraceabilityRuleExecution, filters)

    query = (
        select(TraceabilityRuleExecution)
        .where(TraceabilityRuleExecution.rule_id == rule_id)
        .order_by(TraceabilityRuleExecution.started_at.desc())
    )
    executions = await paginate_query(db, query, skip, limit)

    return TraceabilityRuleExecutionListResponse(
        total=total, items=[TraceabilityRuleExecutionResponse.from_orm(ex) for ex in executions]
    )


@router.post("/rules/{rule_id}/execute", response_model=dict)
def execute_rule(
    rule_id: int, db: Session = Depends(get_sync_db), current_user: User = Depends(get_current_user)
):
    """
    Execute a traceability rule.

    Uses synchronous database session since rule execution engine
    performs complex graph traversal and link creation operations.
    """
    from app.services.rule_execution_engine import RuleExecutionEngine

    engine = RuleExecutionEngine(db)

    with handle_api_error(
        operation="execute_rule",
        status_code=500,
        context={"rule_id": rule_id},
        exception_map={ValueError: 400},
    ):
        result = engine.execute_rule(rule_id)
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
    current_user: User = Depends(get_current_user),
):
    """Get schedule settings for a specific rule."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

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
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
):
    """Get webhook settings for a specific rule (token is hidden)."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

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
    current_user: User = Depends(get_current_user),
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

    new_token = _generate_webhook_token()

    async with transactional_session(db):
        rule.trigger_on_webhook = True
        rule.webhook_token = new_token

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
    current_user: User = Depends(get_current_user),
):
    """Disable webhook triggering for a rule and clear the token."""
    rule = await get_or_404(
        db,
        select(TraceabilityRule).where(TraceabilityRule.id == rule_id),
        f"Rule with id {rule_id}",
    )

    async with transactional_session(db):
        rule.trigger_on_webhook = False
        rule.webhook_token = None

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

    engine = RuleExecutionEngine(db)

    with handle_api_error(
        operation="execute_rule_webhook",
        status_code=500,
        context={"rule_id": rule.id},
        exception_map={ValueError: 400},
    ):
        result = engine.execute_rule(rule.id)
        return {"rule_id": rule.id, "rule_name": rule.name, **result}
