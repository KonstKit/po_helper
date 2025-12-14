from pydantic import BaseModel, Field
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


class TraceabilityRuleInDB(TraceabilityRuleBase):
    id: int
    created_by_id: Optional[int]
    total_executions: int
    successful_executions: int
    failed_executions: int
    last_executed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


# List responses
class TraceabilityRuleListResponse(BaseModel):
    total: int
    items: List[TraceabilityRuleResponse]


class TraceabilityRuleExecutionListResponse(BaseModel):
    total: int
    items: List[TraceabilityRuleExecutionResponse]
