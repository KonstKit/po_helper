from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class RepositoryBase(BaseModel):
    provider: str  # github|gitlab
    repo_slug: str  # org/repo or group/project
    default_branch: Optional[str] = None


class RepositoryCreate(RepositoryBase):
    settings: Optional[dict] = None


class RepositoryUpdate(BaseModel):
    default_branch: Optional[str] = None
    settings: Optional[dict] = None


class Repository(RepositoryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class RepositoryWithProjects(Repository):
    """Repository with list of associated projects"""

    projects: List[dict] = Field(default_factory=list, description="List of associated projects")
