
from typing import List
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Integer
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.models import Project, Task, Sprint, User, Permissions
from app.schemas.project import Project as ProjectSchema, ProjectCreate, ProjectUpdate, ProjectWithStats
from app.api.deps import require_permission, get_current_user
from app.utils import transactional_session, paginate_query, get_or_404, execute_with_lock


router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/", response_model=List[ProjectSchema])
async def get_projects(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_VIEW))
):
    """Get list of projects"""
    start = perf_counter()
    logger.info("projects.list.start skip=%s limit=%s", skip, limit)
    try:
        query = select(Project)
        projects = await paginate_query(db, query, skip, limit)
        logger.info(
            "projects.list.success count=%s duration=%.3f",
            len(projects),
            perf_counter() - start,
        )
        return projects
    except Exception:
        logger.exception(
            "projects.list.error skip=%s limit=%s duration=%.3f",
            skip,
            limit,
            perf_counter() - start,
        )
        raise


@router.get("/{project_id}", response_model=ProjectWithStats)
async def get_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_VIEW))
):
    """Get project with statistics"""
    start = perf_counter()
    logger.info("projects.detail.start project_id=%s", project_id)
    try:
        project = await get_or_404(
            db,
            select(Project).where(Project.id == project_id),
            "Project"
        )

        result = await db.execute(
            select(
                func.count(Task.id).label("total"),
                func.sum(cast((Task.status == "Done"), Integer)).label("completed"),
                func.sum(cast((Task.status == "In Progress"), Integer)).label("in_progress"),
                func.sum(Task.estimate_hours).label("total_estimate"),
                func.sum(Task.spent_hours).label("total_spent"),
            ).where(Task.project_id == project_id)
        )
        stats = result.first()
        total = (stats.total or 0) if stats else 0
        completed = (stats.completed or 0) if stats else 0
        in_progress = (stats.in_progress or 0) if stats else 0
        total_estimate = (stats.total_estimate or 0) if stats else 0
        total_spent = (stats.total_spent or 0) if stats else 0
        completion_percentage = (completed / total * 100) if total else 0

        project_dict = {
            **project.__dict__,
            "total_tasks": total,
            "completed_tasks": completed,
            "in_progress_tasks": in_progress,
            "total_estimate_hours": total_estimate,
            "total_spent_hours": total_spent,
            "completion_percentage": completion_percentage,
        }

        logger.info(
            "projects.detail.success project_id=%s total_tasks=%s completion=%.2f duration=%.3f",
            project_id,
            total,
            completion_percentage,
            perf_counter() - start,
        )
        return project_dict
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "projects.detail.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise


@router.post("/", response_model=ProjectSchema)
async def create_project(
    project: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_CREATE))
):
    """Create new project"""
    start = perf_counter()
    logger.info(
        "projects.create.start jira_key=%s name=%s",
        project.jira_key,
        project.name,
    )
    try:
        sel = select(Project).where(Project.jira_key == project.jira_key)
        result = await execute_with_lock(db, sel)
        if result.scalar_one_or_none():
            logger.warning(
                "projects.create.duplicate jira_key=%s duration=%.3f",
                project.jira_key,
                perf_counter() - start,
            )
            raise HTTPException(status_code=400, detail="Project with this key already exists")

        db_project = Project(**project.dict())
        async with transactional_session(db):
            db.add(db_project)
        await db.refresh(db_project)

        logger.info(
            "projects.create.success project_id=%s duration=%.3f",
            db_project.id,
            perf_counter() - start,
        )
        return db_project
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "projects.create.error jira_key=%s duration=%.3f",
            project.jira_key,
            perf_counter() - start,
        )
        raise


@router.patch("/{project_id}", response_model=ProjectSchema)
async def update_project(
    project_id: int,
    project_update: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_UPDATE))
):
    """Update project"""
    start = perf_counter()
    logger.info("projects.update.start project_id=%s", project_id)
    try:
        project = await get_or_404(
            db,
            select(Project).where(Project.id == project_id),
            "Project"
        )

        update_data = project_update.dict(exclude_unset=True)
        try:
            async with db.begin():
                if "jira_key" in update_data and update_data["jira_key"] is not None:
                    sel = (
                        select(Project)
                        .where(Project.jira_key == update_data["jira_key"])
                        .where(Project.id != project_id)
                    )
                    result = await execute_with_lock(db, sel)
                    if result.scalar_one_or_none():
                        logger.warning(
                            "projects.update.duplicate_jira_key project_id=%s jira_key=%s duration=%.3f",
                            project_id,
                            update_data["jira_key"],
                            perf_counter() - start,
                        )
                        raise HTTPException(status_code=400, detail="Project with this key already exists")

                for field, value in update_data.items():
                    setattr(project, field, value)
        except IntegrityError:
            # Handle race with unique constraint on jira_key
            await db.rollback()
            raise HTTPException(status_code=400, detail="Project with this key already exists")

        await db.refresh(project)

        logger.info(
            "projects.update.success project_id=%s updated_fields=%s duration=%.3f",
            project_id,
            sorted(update_data.keys()),
            perf_counter() - start,
        )
        return project
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "projects.update.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise


@router.delete("/{project_id}")
async def delete_project(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_DELETE))
):
    """Delete project"""
    start = perf_counter()
    logger.info("projects.delete.start project_id=%s", project_id)
    try:
        project = await get_or_404(
            db,
            select(Project).where(Project.id == project_id),
            "Project"
        )

        async with transactional_session(db):
            await db.delete(project)

        logger.info(
            "projects.delete.success project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        return {"message": "Project deleted successfully"}
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "projects.delete.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise


@router.delete("/{project_id}/purge")
async def purge_project_data(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_DELETE))
):
    """Delete all tasks and sprints for a project (keeps project)."""
    start = perf_counter()
    logger.info("projects.purge.start project_id=%s", project_id)
    try:
        async with transactional_session(db):
            result = await db.execute(select(Task).where(Task.project_id == project_id))
            tasks = result.scalars().all()
            for task in tasks:
                await db.delete(task)

            result = await db.execute(select(Sprint).where(Sprint.project_id == project_id))
            sprints = result.scalars().all()
            for sprint in sprints:
                await db.delete(sprint)

        logger.info(
            "projects.purge.success project_id=%s tasks=%s sprints=%s duration=%.3f",
            project_id,
            len(tasks),
            len(sprints),
            perf_counter() - start,
        )
        return {"message": "Purged tasks and sprints", "project_id": project_id}
    except Exception:
        logger.exception(
            "projects.purge.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise
