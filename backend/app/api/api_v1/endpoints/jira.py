from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.config import settings
from app.services.jira_sync import perform_project_sync
from app.tasks.jira_tasks import sync_jira_project
from app.models.settings import IntegrationSetting
from app.core.crypto import encrypt_str
from app.services.jira import JiraAuthError, JiraUnexpectedResponse
from app.services.jira_service import jira_service
from app.models import Project, Task, Sprint, WorkLog, SprintSnapshot
from app.utils import transactional_session, handle_api_error
from sqlalchemy import select
from datetime import datetime
import re
import asyncio
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/connect")
async def connect_to_jira(
    base_url: str = Query(..., description="Jira base URL"),
    email: Optional[str] = Query(None, description="Jira email (optional for PAT)"),
    api_token: str = Query("", description="Jira API token or PAT"),
    save: bool = Query(False, description="Save credentials to database"),
    use_pat: bool = Query(True, description="Use Personal Access Token mode"),
    db: AsyncSession = Depends(get_db),
):
    """Connect to Jira instance and validate credentials."""
    with handle_api_error(
        operation="connect_to_jira",
        exception_map={JiraAuthError: 401, JiraUnexpectedResponse: 502}
    ):
        resolved_use_pat = bool(use_pat)
        connect_email = None if resolved_use_pat else (email or None)

        logger.info("Connecting to Jira: base_url=%s use_pat=%s has_email=%s",
                   base_url, resolved_use_pat, bool(connect_email))

        jira_service.connect(base_url, connect_email, api_token, use_pat=resolved_use_pat)

        # Validate by calling /myself
        logger.info("Validating Jira connection...")
        jira_service.validate()
        logger.info("Jira validation successful")

        if save:
            # Persist credentials in DB
            result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == "jira"))
            row = result.scalar_one_or_none()
            async with transactional_session(db):
                if not row:
                    row = IntegrationSetting(kind="jira")
                    db.add(row)
                row.base_url = (jira_service.base_url or base_url).rstrip('/') if (jira_service.base_url or base_url) else None
                row.email = None if resolved_use_pat else (email or None)
                row.api_token = encrypt_str(api_token) if api_token else row.api_token
            logger.info("Jira credentials saved to database")

        return {"status": "connected", "message": "Successfully connected to Jira"}


@router.get("/status")
async def jira_status():
    mode = 'none'
    if jira_service.bearer_token:
        mode = 'PAT'
    elif jira_service.auth is not None:
        mode = 'Basic'
    return {
        'configured': jira_service.base_url is not None and (jira_service.bearer_token is not None or jira_service.auth is not None),
        'base_url': jira_service.base_url,
        'auth_mode': mode,
    }


@router.get("/projects")
async def list_accessible_projects(q: Optional[str] = None):
    """List Jira projects accessible by current credentials (key, name, id)."""
    with handle_api_error(
        operation="list_accessible_projects",
        exception_map={JiraAuthError: 403, JiraUnexpectedResponse: 502}
    ):
        items = jira_service.list_projects(query=q)
        return { 'count': len(items), 'projects': items }


@router.get("/projects/{project_key}/check")
async def check_project_key(project_key: str):
    """Check whether a project key exists and is accessible."""
    try:
        data = jira_service.get_project(project_key)
        return { 'exists': True, 'project': data }
    except Exception as e:
        return { 'exists': False, 'detail': str(e) }


@router.get("/projects/{project_key}/boards")
async def list_boards(project_key: str):
    """List Agile boards for a given project key."""
    boards = jira_service.list_boards_for_project(project_key)
    return { 'count': len(boards), 'boards': boards }


@router.get("/projects/{project_key}")
async def get_jira_project(project_key: str):
    """Get project details from Jira"""
    with handle_api_error(operation="get_jira_project", status_code=404, context={"project_key": project_key}):
        project = jira_service.get_project(project_key)
        return project


@router.get("/projects/{project_key}/issues")
async def get_project_issues(
    project_key: str,
    max_results: int = 100
):
    """Get all issues for a project from Jira"""
    with handle_api_error(
        operation="get_project_issues",
        context={"project_key": project_key, "max_results": max_results},
        exception_map={JiraAuthError: 403, JiraUnexpectedResponse: 502}
    ):
        issues = jira_service.get_project_issues(project_key, max_results)
        return {
            "total": len(issues),
            "issues": issues
        }


@router.post("/projects/{project_key}/sync")
async def sync_project_data(
    project_key: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Sync project data from Jira to database.
    Be tolerant: if fetching project meta fails (e.g., restricted), still try to sync issues.
    """
    # Try fetching project info, but don't fail the whole sync if it errors
    logger = logging.getLogger(__name__)
    jira_project = None
    try:
        logger.info("Sync start project_key=%s", project_key)
        jira_project = jira_service.get_project(project_key)
    except Exception as e:
        # Log and continue to syncing issues (many setups restrict /project but allow /search)
        logger.warning("get_project failed for %s: %s", project_key, e)

    # Ensure DB project exists
    result = await db.execute(select(Project).where(Project.jira_key == project_key))
    db_project = result.scalar_one_or_none()

    if not db_project:
        db_project = Project(
            jira_key=project_key,
            name=(jira_project or {}).get("name", project_key),
            description=(jira_project or {}).get("description"),
        )
        async with transactional_session(db):
            db.add(db_project)
        await db.refresh(db_project)

    # Dispatch sync via Celery (preferred) or FastAPI background task (fallback)
    task_id = None
    use_celery = getattr(settings, 'CELERY_ENABLED', True)

    # Skip Celery in development if explicitly disabled
    if use_celery and getattr(settings, 'is_development', False):
        if not getattr(settings, 'CELERY_USE_IN_DEV', True):
            logger.info('Skipping Celery in development; using FastAPI background task')
            use_celery = False

    if use_celery:
        try:
            # Dispatch to Celery worker - non-blocking, doesn't hold event loop
            result = sync_jira_project.delay(project_key, db_project.id)
            task_id = result.id
            logger.info(
                'Jira sync dispatched to Celery: project=%s task_id=%s',
                project_key, task_id
            )
            return {
                "status": "syncing",
                "message": f"Started Celery sync for project {project_key}",
                "project_id": db_project.id,
                "task_id": task_id,
                "method": "celery"
            }
        except Exception as exc:
            logger.warning('Celery dispatch failed, falling back to FastAPI: %s', exc)
            use_celery = False

    # Fallback: FastAPI background task (still async, but in-process)
    logger.info('Dispatching Jira sync via FastAPI background task for project=%s', project_key)

    async def _async_sync_job(p_key: str, p_id: int) -> None:
        """Wrapper to run async sync in FastAPI background task."""
        try:
            logger.info('FastAPI background task started for project=%s', p_key)
            await perform_project_sync(p_key, p_id)
            logger.info('FastAPI background task completed for project=%s', p_key)
        except Exception as exc:
            logger.error('FastAPI background task failed for project=%s: %s', p_key, exc, exc_info=True)

    background_tasks.add_task(_async_sync_job, project_key, db_project.id)

    return {
        "status": "syncing",
        "message": f"Started FastAPI sync for project {project_key}",
        "project_id": db_project.id,
        "method": "fastapi_background"
    }


@router.get("/sprints/{board_id}/active")
async def get_active_sprints(board_id: int):
    """Get active sprints for a board"""
    with handle_api_error(operation="get_active_sprints", context={"board_id": board_id}):
        sprints = jira_service.get_active_sprints(board_id)
        return {
            "total": len(sprints),
            "sprints": sprints
        }


@router.get("/issues/{issue_key}/worklogs")
async def get_issue_worklogs(issue_key: str):
    """Get worklogs for an issue"""
    with handle_api_error(operation="get_issue_worklogs", context={"issue_key": issue_key}):
        worklogs = jira_service.get_worklogs(issue_key)
        return {
            "total": len(worklogs),
            "worklogs": worklogs
        }
@router.post("/connect_pat")
async def connect_to_jira_pat(
    base_url: str,
    api_token: str,
    save: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Convenience endpoint to connect with PAT (Bearer) explicitly and persist credentials."""
    return await connect_to_jira(base_url=base_url, email=None, api_token=api_token, save=save, use_pat=True, db=db)


@router.get("/debug/{project_key}")
async def debug_jira_project(project_key: str):
    """Debug endpoint to check Jira permissions and data availability for a project."""
    logger = logging.getLogger(__name__)
    results = {
        "project_key": project_key,
        "checks": {},
        "errors": []
    }

    # Check 1: Can we get the project?
    try:
        project = jira_service.get_project(project_key)
        results["checks"]["project_access"] = {
            "success": True,
            "data": project
        }
    except Exception as e:
        results["checks"]["project_access"] = {
            "success": False,
            "error": str(e)
        }
        results["errors"].append(f"Cannot access project: {e}")

    # Check 2: Can we search for issues?
    try:
        issues = jira_service.get_project_issues(project_key, max_results=5)
        results["checks"]["issue_search"] = {
            "success": True,
            "count": len(issues),
            "sample": issues[:2] if issues else []
        }
        if not issues:
            results["errors"].append("No issues found - project may be empty or check 'Browse Projects' permission")
    except Exception as e:
        results["checks"]["issue_search"] = {
            "success": False,
            "error": str(e)
        }
        results["errors"].append(f"Cannot search issues: {e}")

    # Check 3: Can we access boards?
    try:
        boards = jira_service.list_boards_for_project(project_key)
        results["checks"]["board_access"] = {
            "success": True,
            "count": len(boards),
            "boards": [{"id": b.get("id"), "name": b.get("name")} for b in boards]
        }

        # Check 4: Can we get sprints from first board?
        if boards:
            first_board = boards[0]
            try:
                sprints = jira_service.list_sprints(first_board.get("id"))
                results["checks"]["sprint_access"] = {
                    "success": True,
                    "board_id": first_board.get("id"),
                    "count": len(sprints),
                    "sample": [{"id": s.get("id"), "name": s.get("name"), "state": s.get("state")}
                              for s in sprints[:3]]
                }
            except Exception as e:
                results["checks"]["sprint_access"] = {
                    "success": False,
                    "board_id": first_board.get("id"),
                    "error": str(e)
                }
                results["errors"].append(f"Cannot access sprints: {e}")
        else:
            results["checks"]["sprint_access"] = {
                "success": False,
                "error": "No boards found"
            }
    except Exception as e:
        results["checks"]["board_access"] = {
            "success": False,
            "error": str(e)
        }
        results["errors"].append(f"Cannot access boards: {e}")

    # Summary
    results["summary"] = {
        "all_checks_passed": len(results["errors"]) == 0,
        "recommendations": []
    }

    if results["errors"]:
        if "Cannot access project" in str(results["errors"]):
            results["summary"]["recommendations"].append(
                "Ensure API token has 'Browse Projects' permission in Jira"
            )
        if "No issues found" in str(results["errors"]):
            results["summary"]["recommendations"].append(
                "Check if project has issues or if 'Browse Projects' and 'View Issues' permissions are granted"
            )
        if "Cannot access boards" in str(results["errors"]):
            results["summary"]["recommendations"].append(
                "Ensure Jira Software/Agile features are enabled and accessible"
            )

    return results
