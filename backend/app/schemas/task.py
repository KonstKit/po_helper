from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


class TaskBase(BaseModel):
    jira_id: str

    @staticmethod
    def _ensure_list(value):
        if value is None:
            return None
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            # Try comma-separated fallback
            parts = [p.strip() for p in value.split(",") if p.strip()]
            return parts or None
        # Unknown type -> drop
        return None

    @staticmethod
    def _ensure_dict(value):
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        # Unknown type -> drop
        return None

    @field_validator("blocked_by", "blocks", "labels", "components", mode="before")
    def _validate_lists(cls, v):
        return TaskBase._ensure_list(v)

    @field_validator("custom_fields", mode="before")
    def _validate_custom_fields(cls, v):
        return TaskBase._ensure_dict(v)

    key: str
    summary: str
    description: Optional[str] = None
    task_type: Optional[str] = None
    status: str
    priority: Optional[str] = None
    assignee_email: Optional[str] = None
    assignee_name: Optional[str] = None
    reporter_email: Optional[str] = None
    reporter_name: Optional[str] = None
    estimate_hours: Optional[float] = None
    spent_hours: Optional[float] = None
    remaining_hours: Optional[float] = None
    is_blocker: bool = False
    blocked_by: Optional[List[str]] = None
    blocks: Optional[List[str]] = None
    created_date: Optional[datetime] = None
    updated_date: Optional[datetime] = None
    resolved_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    labels: Optional[List[str]] = None
    components: Optional[List[str]] = None
    custom_fields: Optional[Dict[str, Any]] = None
    # Business value (optional)
    business_value: Optional[float] = None
    value_delivered: Optional[bool] = None
    roi: Optional[float] = None


class TaskCreate(TaskBase):
    project_id: int
    sprint_id: Optional[int] = None


class TaskUpdate(BaseModel):
    status: Optional[str] = None
    assignee_email: Optional[str] = None
    assignee_name: Optional[str] = None
    estimate_hours: Optional[float] = None
    spent_hours: Optional[float] = None
    remaining_hours: Optional[float] = None
    is_blocker: Optional[bool] = None
    sprint_id: Optional[int] = None
    business_value: Optional[float] = None
    value_delivered: Optional[bool] = None
    roi: Optional[float] = None


class TaskInDB(TaskBase):
    id: int
    project_id: Optional[int] = None  # Allow NULL project_id for orphaned tasks
    sprint_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Task(TaskInDB):
    pass


class TaskWithRelations(Task):
    project_name: Optional[str] = None
    sprint_name: Optional[str] = None
    deviation_hours: Optional[float] = None
    completion_rate: Optional[float] = None
