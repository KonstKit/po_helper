from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ProjectBase(BaseModel):
    jira_key: str
    name: str
    description: Optional[str] = None
    budget: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: str = "active"
    meta: Optional[Dict[str, Any]] = None


class ProjectCreate(ProjectBase):
    owner_id: int


class ProjectUpdate(BaseModel):
    jira_key: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    budget: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None


class ProjectInDB(ProjectBase):
    id: int
    owner_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class Project(ProjectInDB):
    pass


class ProjectWithStats(Project):
    total_tasks: int = 0
    completed_tasks: int = 0
    in_progress_tasks: int = 0
    total_estimate_hours: float = 0
    total_spent_hours: float = 0
    completion_percentage: float = 0
    velocity: Optional[float] = None
