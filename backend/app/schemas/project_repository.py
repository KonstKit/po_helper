from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict


class ProjectRepositoryBase(BaseModel):
    project_id: int
    repository_id: int
    is_primary: bool = True


class ProjectRepositoryCreate(ProjectRepositoryBase):
    pass


class ProjectRepositoryUpdate(BaseModel):
    is_primary: Optional[bool] = None


class ProjectRepository(ProjectRepositoryBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class RepositoryInfo(BaseModel):
    id: int
    provider: str  # github|gitlab
    repo_slug: str  # org/repo or group/project
    default_branch: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class ProjectRepositoryWithDetails(ProjectRepository):
    repository: RepositoryInfo


class ProjectRepositoryBinding(BaseModel):
    """Schema for binding repository to project via URL or slug"""

    project_id: int
    repository_url: Optional[str] = Field(
        None, description="Full repository URL (e.g., https://github.com/org/repo)"
    )
    repo_slug: Optional[str] = Field(None, description="Repository slug (e.g., org/repo)")
    provider: Optional[str] = Field(None, description="Provider: github or gitlab")
    is_primary: bool = Field(
        True, description="Whether this is the primary repository for the project"
    )
