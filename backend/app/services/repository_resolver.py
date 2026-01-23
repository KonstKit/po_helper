"""Service for resolving which repository to use for a project"""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models import Project, Repository, ProjectRepository


class RepositoryResolver:
    """Resolver for determining which repository to use for a project"""

    @staticmethod
    async def get_primary_repository(project_id: int, db: AsyncSession) -> Optional[Repository]:
        """Get the primary repository for a project"""
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.repository))
            .where(ProjectRepository.project_id == project_id, ProjectRepository.is_primary)
        )
        project_repo = result.scalar_one_or_none()

        if project_repo:
            return project_repo.repository

        # Fallback: get first repository if no primary is set
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.repository))
            .where(ProjectRepository.project_id == project_id)
            .order_by(ProjectRepository.created_at)
            .limit(1)
        )
        project_repo = result.scalar_one_or_none()

        return project_repo.repository if project_repo else None

    @staticmethod
    async def get_all_repositories(project_id: int, db: AsyncSession) -> List[Repository]:
        """Get all repositories linked to a project"""
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.repository))
            .where(ProjectRepository.project_id == project_id)
            .order_by(ProjectRepository.is_primary.desc(), ProjectRepository.created_at)
        )
        project_repos = result.scalars().all()

        return [pr.repository for pr in project_repos]

    @staticmethod
    async def get_repository_by_provider(
        project_id: int, provider: str, db: AsyncSession
    ) -> Optional[Repository]:
        """Get a repository for a project by provider (github/gitlab)"""
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.repository))
            .join(Repository)
            .where(
                ProjectRepository.project_id == project_id, Repository.provider == provider.lower()
            )
            .order_by(ProjectRepository.is_primary.desc())
            .limit(1)
        )
        project_repo = result.scalar_one_or_none()

        return project_repo.repository if project_repo else None

    @staticmethod
    async def get_project_by_repository(repository_id: int, db: AsyncSession) -> Optional[Project]:
        """Get the primary project for a repository"""
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.project))
            .where(
                ProjectRepository.repository_id == repository_id,
                ProjectRepository.is_primary,
            )
        )
        project_repo = result.scalar_one_or_none()

        if project_repo:
            return project_repo.project

        # Fallback: get first project if no primary is set
        result = await db.execute(
            select(ProjectRepository)
            .options(selectinload(ProjectRepository.project))
            .where(ProjectRepository.repository_id == repository_id)
            .order_by(ProjectRepository.created_at)
            .limit(1)
        )
        project_repo = result.scalar_one_or_none()

        return project_repo.project if project_repo else None


repository_resolver = RepositoryResolver()
