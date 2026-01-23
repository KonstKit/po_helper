from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


# React Flow node/edge schemas
class ReactFlowNode(BaseModel):
    id: str
    type: str
    position: Dict[str, float]  # { x: float, y: float }
    data: Dict[str, Any]


class ReactFlowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None


class FlowJSON(BaseModel):
    nodes: List[ReactFlowNode]
    edges: List[ReactFlowEdge]
    version: Optional[str] = "1.0"
    metadata: Optional[Dict[str, Any]] = None


# Traceability Rule schemas
class TraceabilityRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    flow_json: FlowJSON
    enabled: bool = True
    category: str = Field(default="custom", pattern="^(basic|advanced|custom)$")
    tags: List[str] = Field(default_factory=list)
    project_id: Optional[int] = None
    # Scheduling fields
    schedule_cron: Optional[str] = Field(None, max_length=100)
    schedule_enabled: bool = False
    trigger_on_webhook: bool = False


class TraceabilityRuleCreate(TraceabilityRuleBase):
    pass


class TraceabilityRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    flow_json: Optional[FlowJSON] = None
    enabled: Optional[bool] = None
    category: Optional[str] = Field(None, pattern="^(basic|advanced|custom)$")
    tags: Optional[List[str]] = None
    project_id: Optional[int] = None
    # Scheduling fields
    schedule_cron: Optional[str] = Field(None, max_length=100)
    schedule_enabled: Optional[bool] = None
    trigger_on_webhook: Optional[bool] = None


class TraceabilityRuleInDB(TraceabilityRuleBase):
    id: int
    created_by_id: Optional[int]
    total_executions: int
    successful_executions: int
    failed_executions: int
    last_executed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TraceabilityRuleResponse(TraceabilityRuleInDB):
    """Response schema with additional computed fields"""

    success_rate: Optional[float] = None

    @classmethod
    def from_db(cls, db_rule):
        """Create response from database model"""
        data = {
            "id": db_rule.id,
            "name": db_rule.name,
            "description": db_rule.description,
            "flow_json": db_rule.flow_json,
            "enabled": db_rule.enabled,
            "category": db_rule.category,
            "tags": db_rule.tags or [],
            "project_id": db_rule.project_id,
            "created_by_id": db_rule.created_by_id,
            "total_executions": db_rule.total_executions,
            "successful_executions": db_rule.successful_executions,
            "failed_executions": db_rule.failed_executions,
            "last_executed_at": db_rule.last_executed_at,
            "created_at": db_rule.created_at,
            "updated_at": db_rule.updated_at,
        }

        # Calculate success rate
        if db_rule.total_executions > 0:
            data["success_rate"] = (db_rule.successful_executions / db_rule.total_executions) * 100
        else:
            data["success_rate"] = None

        return cls(**data)


# Rule Execution schemas
class TraceabilityRuleExecutionCreate(BaseModel):
    rule_id: int
    execution_context: Optional[Dict[str, Any]] = None


class TraceabilityRuleExecutionResponse(BaseModel):
    id: int
    rule_id: int
    status: str
    started_at: datetime
    completed_at: Optional[datetime]
    links_created: int
    links_updated: int
    artifacts_processed: int
    error_message: Optional[str]
    error_details: Optional[Dict[str, Any]]

    model_config = ConfigDict(from_attributes=True)


# List responses
class TraceabilityRuleListResponse(BaseModel):
    total: int
    items: List[TraceabilityRuleResponse]


class TraceabilityRuleExecutionListResponse(BaseModel):
    total: int
    items: List[TraceabilityRuleExecutionResponse]


# =============================================================================
# Validation Schemas (mirroring frontend ruleValidation.ts)
# =============================================================================


class ValidationError(BaseModel):
    """Single validation error."""

    type: str = "error"
    message: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


class ValidationWarning(BaseModel):
    """Single validation warning."""

    type: str = "warning"
    message: str
    node_id: Optional[str] = None
    edge_id: Optional[str] = None


class ValidationResult(BaseModel):
    """Result of flow validation - matches frontend ValidationResult interface."""

    valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationWarning]


class FlowValidationRequest(BaseModel):
    """Request body for flow validation endpoint."""

    flow_json: FlowJSON


# =============================================================================
# Scheduling Schemas
# =============================================================================


class RuleScheduleUpdate(BaseModel):
    """Request body for updating rule schedule settings."""

    schedule_cron: Optional[str] = Field(
        None, max_length=100, description="Cron expression (e.g., '0 */6 * * *')"
    )
    schedule_enabled: Optional[bool] = Field(None, description="Enable/disable scheduled execution")


class RuleScheduleResponse(BaseModel):
    """Response for rule schedule settings."""

    rule_id: int
    schedule_cron: Optional[str]
    schedule_enabled: bool
    next_scheduled_run: Optional[datetime]


class RuleWebhookResponse(BaseModel):
    """Response for rule webhook settings."""

    rule_id: int
    trigger_on_webhook: bool
    webhook_token: Optional[str] = Field(
        None, description="Webhook token (only shown once on generation)"
    )
    webhook_url: Optional[str] = Field(
        None, description="Full webhook URL for triggering this rule"
    )
