from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from urllib.parse import urlparse
from app.core.database import get_db
from app.models import Project, Repository, ProjectRepository, IntegrationSetting
from app.schemas.project_repository import (
    ProjectRepositoryWithDetails,
    ProjectRepositoryBinding,
    RepositoryInfo,
)
from app.schemas.repository import RepositoryWithProjects
from app.utils import transactional_session, get_by_id_or_404, get_or_404

router = APIRouter()


def parse_repository_url(url: str) -> tuple[str, str]:
    """Parse repository URL to extract provider and slug. Supports nested GitLab namespaces.
    Returns provider (github/gitlab) and repo slug (namespace/path)."""
    url = url.strip()
    host = ""
    path_component = ""

    if url.startswith("git@"):
        try:
            _, rest = url.split("@", 1)
            host, path_component = rest.split(":", 1)
        except ValueError as exc:
            raise ValueError(f"Could not parse repository URL: {url}") from exc
    else:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Could not parse repository URL: {url}")
        host = parsed.hostname or parsed.netloc
        path_component = parsed.path

    host = host.lower().strip()
    path_component = path_component.strip().rstrip("/")
    if path_component.endswith(".git"):
        path_component = path_component[:-4]
    path_component = path_component.lstrip("/")

    if not path_component:
        raise ValueError(f"Could not parse repository URL: {url}")

    if "github" in host:
        provider = "github"
        segments = path_component.split("/")
        if len(segments) < 2:
            raise ValueError(f"Could not parse GitHub repository URL: {url}")
        slug = "/".join(segments[:2])
    else:
        provider = "gitlab"
        slug = path_component

    return provider, slug


@router.get(
    "/projects/{project_id}/repositories", response_model=List[ProjectRepositoryWithDetails]
)
async def get_project_repositories(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get all repositories linked to a project"""
    result = await db.execute(
        select(ProjectRepository)
        .options(selectinload(ProjectRepository.repository))
        .where(ProjectRepository.project_id == project_id)
        .order_by(ProjectRepository.is_primary.desc(), ProjectRepository.created_at)
    )
    project_repos = result.scalars().all()

    return [
        ProjectRepositoryWithDetails(
            id=pr.id,
            project_id=pr.project_id,
            repository_id=pr.repository_id,
            is_primary=pr.is_primary,
            created_at=pr.created_at,
            updated_at=pr.updated_at,
            repository=RepositoryInfo(
                id=pr.repository.id,
                provider=pr.repository.provider,
                repo_slug=pr.repository.repo_slug,
                default_branch=pr.repository.default_branch,
            ),
        )
        for pr in project_repos
    ]


@router.post("/projects/{project_id}/repositories", response_model=ProjectRepositoryWithDetails)
async def bind_repository_to_project(
    project_id: int, binding: ProjectRepositoryBinding, db: AsyncSession = Depends(get_db)
):
    """Bind a repository to a project by URL or slug"""
    # Verify project exists
    await get_by_id_or_404(db, Project, project_id)

    # Determine provider and slug
    provider = None
    repo_slug = None

    if binding.repository_url:
        try:
            provider, repo_slug = parse_repository_url(binding.repository_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif binding.repo_slug and binding.provider:
        provider = binding.provider.lower()
        repo_slug = binding.repo_slug
    else:
        raise HTTPException(
            status_code=400,
            detail="Either repository_url or both repo_slug and provider must be provided",
        )

    # Verify provider configuration exists
    result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == provider))
    integration = result.scalar_one_or_none()
    if not integration or not integration.api_token:
        raise HTTPException(
            status_code=400, detail=f"{provider.capitalize()} integration is not configured"
        )

    # Check if repository already exists
    repo_result = await db.execute(
        select(Repository).where(Repository.provider == provider, Repository.repo_slug == repo_slug)
    )
    repository: Repository | None = repo_result.scalar_one_or_none()

    if not repository:
        # Create new repository
        repository = Repository(provider=provider, repo_slug=repo_slug)
        db.add(repository)
        await db.flush()
    assert repository is not None

    # Check if binding already exists
    result = await db.execute(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.repository_id == repository.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Repository is already linked to this project")

    # If this should be primary, unset other primaries
    if binding.is_primary:
        primaries_stmt = select(ProjectRepository).where(
            ProjectRepository.project_id == project_id, ProjectRepository.is_primary
        )
        existing_primaries: List[ProjectRepository] = list(
            (await db.execute(primaries_stmt)).scalars().all()
        )
        for pr in existing_primaries:
            pr.is_primary = False

    # Create new binding
    project_repo = ProjectRepository(
        project_id=project_id, repository_id=repository.id, is_primary=binding.is_primary
    )
    async with transactional_session(db):
        db.add(project_repo)
    await db.refresh(project_repo)
    await db.refresh(repository)

    return ProjectRepositoryWithDetails(
        id=project_repo.id,
        project_id=project_repo.project_id,
        repository_id=project_repo.repository_id,
        is_primary=project_repo.is_primary,
        created_at=project_repo.created_at,
        updated_at=project_repo.updated_at,
        repository=RepositoryInfo(
            id=repository.id,
            provider=repository.provider,
            repo_slug=repository.repo_slug,
            default_branch=repository.default_branch,
        ),
    )


@router.delete("/projects/{project_id}/repositories/{repository_id}")
async def unbind_repository_from_project(
    project_id: int, repository_id: int, db: AsyncSession = Depends(get_db)
):
    """Remove repository binding from a project"""
    project_repo = await get_or_404(
        db,
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.repository_id == repository_id,
        ),
        "Repository binding",
    )

    async with transactional_session(db):
        await db.delete(project_repo)

    return {"status": "success", "message": "Repository unbound from project"}


@router.put("/projects/{project_id}/repositories/{repository_id}/primary")
async def set_primary_repository(
    project_id: int, repository_id: int, db: AsyncSession = Depends(get_db)
):
    """Set a repository as the primary for a project"""
    # Find the binding
    project_repo = await get_or_404(
        db,
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.repository_id == repository_id,
        ),
        "Repository binding",
    )

    # Unset other primaries
    result = await db.execute(
        select(ProjectRepository).where(
            ProjectRepository.project_id == project_id,
            ProjectRepository.is_primary,
            ProjectRepository.repository_id != repository_id,
        )
    )
    other_primaries = result.scalars().all()
    async with transactional_session(db):
        for pr in other_primaries:
            pr.is_primary = False

        # Set this one as primary
        project_repo.is_primary = True

    return {"status": "success", "message": "Primary repository updated"}


@router.get("/repositories", response_model=List[RepositoryWithProjects])
async def list_all_repositories(
    provider: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all repositories with their associated projects (paginated)."""
    query = select(Repository).options(
        selectinload(Repository.project_repositories).selectinload(ProjectRepository.project)
    )

    if provider:
        query = query.where(Repository.provider == provider.lower())

    query = query.order_by(Repository.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    repositories = result.scalars().all()

    return [
        RepositoryWithProjects(
            id=repo.id,
            provider=repo.provider,
            repo_slug=repo.repo_slug,
            default_branch=repo.default_branch,
            created_at=repo.created_at,
            updated_at=repo.updated_at,
            projects=[
                {
                    "id": pr.project.id,
                    "jira_key": pr.project.jira_key,
                    "name": pr.project.name,
                    "is_primary": pr.is_primary,
                }
                for pr in repo.project_repositories
            ],
        )
        for repo in repositories
    ]


@router.get("/projects/{project_id}/primary-repository", response_model=Optional[RepositoryInfo])
async def get_primary_repository(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get the primary repository for a project"""
    result = await db.execute(
        select(ProjectRepository)
        .options(selectinload(ProjectRepository.repository))
        .where(ProjectRepository.project_id == project_id, ProjectRepository.is_primary)
    )
    project_repo = result.scalar_one_or_none()

    if not project_repo:
        return None

    return RepositoryInfo(
        id=project_repo.repository.id,
        provider=project_repo.repository.provider,
        repo_slug=project_repo.repository.repo_slug,
        default_branch=project_repo.repository.default_branch,
    )
