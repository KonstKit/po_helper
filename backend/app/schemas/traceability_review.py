"""Pydantic schemas for the traceability manual-review queue (plan_70)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.traceability_review import TraceabilityReviewItem


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: Optional[str] = None
    project_id: Optional[int] = None
    artifact_id: int
    rule_id: Optional[int] = None
    rule_execution_id: Optional[int] = None
    node_id: str
    status: str
    priority: str
    reason: Optional[str] = None
    assigned_to_id: Optional[int] = None
    created_by_id: Optional[int] = None
    resolved_by_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    meta: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_db(cls, item: TraceabilityReviewItem) -> "ReviewItemResponse":
        return cls.model_validate(item)


class ReviewItemListResponse(BaseModel):
    total: int
    items: List[ReviewItemResponse]


class ReviewTransitionRequest(BaseModel):
    """Optional payload for resolve/reject/reopen transitions."""

    note: Optional[str] = Field(default=None, max_length=2000)
