from typing import List
import logging
from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, Integer, delete, or_
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.models import Project, Task, Sprint, User, Permissions
from app.schemas.project import (
    Project as ProjectSchema,
    ProjectCreate,
    ProjectUpdate,
    ProjectWithStats,
)
from app.api.deps import (
    can_access_project,
    ensure_project_access,
    has_admin_access,
    require_permission,
)
from app.core.request_context import get_token_tenant_id
from app.utils import paginate_query, transactional_session, execute_with_lock


router = APIRouter()

logger = logging.getLogger(__name__)


def _visible_projects_query(current_user: User):
    # eager-load owner: serialization touches it for every row and lazy
    # loads would turn the list endpoint into an N+1
    query = select(Project).options(selectinload(Project.owner)).order_by(Project.id.asc())
    token_tenant_id = get_token_tenant_id()

    if token_tenant_id is not None:
        return query.where(
            Project.meta.is_not(None),
            Project.meta["tenant_id"].as_string() == str(token_tenant_id),
        )

    return query.where(
        or_(
            Project.meta.is_(None),
            Project.meta["tenant_id"].as_string().is_(None),
        )
    )


def _project_access_candidate_query(current_user: User):
    query = _visible_projects_query(current_user)
    if has_admin_access(current_user):
        return query

    return query.where(
        or_(
            Project.owner_id == current_user.id,
            Project.meta.is_not(None),
        )
    )


@router.get("/", response_model=List[ProjectSchema])
async def get_projects(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_VIEW)),
):
    """Get list of projects"""
    start = perf_counter()
    logger.info("projects.list.start skip=%s limit=%s", skip, limit)
    try:
        if limit <= 0:
            logger.info(
                "projects.list.success count=0 duration=%.3f",
                perf_counter() - start,
            )
            return []

        query = _visible_projects_query(current_user)
        if has_admin_access(current_user):
            projects: list[Project] = await paginate_query(db, query, skip, limit)
        else:
            projects = []
            skipped_visible = 0
            stream = await db.stream_scalars(_project_access_candidate_query(current_user))
            try:
                async for project in stream:
                    if not can_access_project(project, current_user):
                        continue
                    if skipped_visible < skip:
                        skipped_visible += 1
                        continue
                    projects.append(project)
                    if len(projects) >= limit:
                        break
            finally:
                await stream.close()
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
    current_user: User = Depends(require_permission(Permissions.PROJECT_VIEW)),
):
    """Get project with statistics"""
    start = perf_counter()
    logger.info("projects.detail.start project_id=%s", project_id)
    try:
        project = await ensure_project_access(project_id, db, current_user)

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
    current_user: User = Depends(require_permission(Permissions.PROJECT_CREATE)),
):
    """Create new project"""
    start = perf_counter()
    logger.info(
        "projects.create.start jira_key=%s name=%s",
        project.jira_key,
        project.name,
    )
    try:
        if not current_user.is_active:
            raise HTTPException(status_code=403, detail="Inactive user")

        payload = project.model_dump()
        token_tenant_id = get_token_tenant_id()
        project_meta = payload.get("meta")
        if project_meta is None:
            project_meta = {}
        if not isinstance(project_meta, dict):
            raise HTTPException(status_code=400, detail="meta must be an object")

        project_tenant_id = project_meta.get("tenant_id")
        if token_tenant_id is not None:
            if project_tenant_id is None:
                project_meta["tenant_id"] = token_tenant_id
            elif str(project_tenant_id).strip() != str(token_tenant_id):
                raise HTTPException(status_code=403, detail="Project tenant mismatch")
        elif project_tenant_id is not None:
            raise HTTPException(status_code=403, detail="Tenant-scoped token is required")

        payload["meta"] = project_meta or None

        if not has_admin_access(current_user):
            owner_id = payload.get("owner_id")
            if owner_id is not None and owner_id != current_user.id:
                raise HTTPException(status_code=403, detail="owner_id must match current user")
            payload["owner_id"] = current_user.id

            enforced_meta = dict(payload.get("meta") or {})
            member_ids = enforced_meta.get("member_ids")
            if not isinstance(member_ids, list):
                member_ids = []
            if current_user.id not in member_ids:
                member_ids.append(current_user.id)
            enforced_meta["member_ids"] = member_ids
            payload["meta"] = enforced_meta or None

        sel = select(Project).where(Project.jira_key == project.jira_key)
        result = await execute_with_lock(db, sel)
        if result.scalar_one_or_none():
            logger.warning(
                "projects.create.duplicate jira_key=%s duration=%.3f",
                project.jira_key,
                perf_counter() - start,
            )
            raise HTTPException(status_code=400, detail="Project with this key already exists")

        db_project = Project(**payload)
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
    current_user: User = Depends(require_permission(Permissions.PROJECT_UPDATE)),
):
    """Update project"""
    start = perf_counter()
    logger.info("projects.update.start project_id=%s", project_id)
    try:
        project = await ensure_project_access(project_id, db, current_user)

        update_data = project_update.model_dump(exclude_unset=True)
        if "meta" in update_data:
            meta_value = update_data["meta"]
            if meta_value is not None and not isinstance(meta_value, dict):
                raise HTTPException(status_code=400, detail="meta must be an object")

            token_tenant_id = get_token_tenant_id()
            target_meta = dict(meta_value or {})
            target_tenant_id = target_meta.get("tenant_id")
            if token_tenant_id is not None:
                if target_tenant_id is None:
                    target_meta["tenant_id"] = token_tenant_id
                elif str(target_tenant_id).strip() != str(token_tenant_id):
                    raise HTTPException(status_code=403, detail="Project tenant mismatch")
            elif target_tenant_id is not None and not has_admin_access(current_user):
                raise HTTPException(status_code=403, detail="Tenant-scoped token is required")
            update_data["meta"] = target_meta or None

        try:
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
                    raise HTTPException(
                        status_code=400, detail="Project with this key already exists"
                    )

            for field, value in update_data.items():
                setattr(project, field, value)
            await db.commit()
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
    current_user: User = Depends(require_permission(Permissions.PROJECT_DELETE)),
):
    """Delete project"""
    start = perf_counter()
    logger.info("projects.delete.start project_id=%s", project_id)
    try:
        project = await ensure_project_access(project_id, db, current_user)

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
    current_user: User = Depends(require_permission(Permissions.PROJECT_DELETE)),
):
    """Delete all tasks and sprints for a project (keeps project)."""
    start = perf_counter()
    logger.info("projects.purge.start project_id=%s", project_id)
    try:
        await ensure_project_access(project_id, db, current_user)
        async with transactional_session(db):
            # Bulk delete tasks - O(1) instead of O(n) queries
            tasks_result = await db.execute(
                delete(Task).where(Task.project_id == project_id).returning(Task.id)
            )
            deleted_task_ids = tasks_result.scalars().all()

            # Bulk delete sprints - O(1) instead of O(n) queries
            sprints_result = await db.execute(
                delete(Sprint).where(Sprint.project_id == project_id).returning(Sprint.id)
            )
            deleted_sprint_ids = sprints_result.scalars().all()

        logger.info(
            "projects.purge.success project_id=%s tasks=%s sprints=%s duration=%.3f",
            project_id,
            len(deleted_task_ids),
            len(deleted_sprint_ids),
            perf_counter() - start,
        )
        return {
            "message": "Purged tasks and sprints",
            "project_id": project_id,
            "tasks_deleted": len(deleted_task_ids),
            "sprints_deleted": len(deleted_sprint_ids),
        }
    except Exception:
        logger.exception(
            "projects.purge.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise
