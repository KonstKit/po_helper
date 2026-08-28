import asyncio
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from time import perf_counter
from app.api.deps import require_integration_access, require_integration_permission
from app.models.rbac import Permissions
from app.core.database import get_db
from app.core.config import settings
from app.core.crypto import encrypt_integration_secret
from app.core.metrics import metrics
from app.services.jira_sync import perform_project_sync
from app.tasks.jira_tasks import sync_jira_project
from app.models.settings import IntegrationSetting
from app.models import User
from app.services.jira import JiraAuthError, JiraUnexpectedResponse
from app.services.jira_service import jira_service
from app.services.sync_tracking import reserve_project_sync_task_lease
from app.models import Project
from app.utils import transactional_session, handle_api_error
from sqlalchemy import select
import logging

router = APIRouter()
logger = logging.getLogger(__name__)
JIRA_PROJECT_BOARDS_SLOW_THRESHOLD_SECONDS = 3.0


class JiraConnectRequest(BaseModel):
    base_url: str
    api_token: str
    email: Optional[str] = None
    save: bool = False
    use_pat: bool = True


class JiraPatConnectRequest(BaseModel):
    base_url: str
    api_token: str
    save: bool = True


def _encrypt_saved_token(token: str) -> str:
    try:
        encrypted = encrypt_integration_secret(token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if encrypted is None:
        raise HTTPException(status_code=503, detail="Failed to persist Jira credentials.")
    return encrypted


def _normalize_http_base_url(base_url: str, provider: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {provider} base_url. Only http/https URLs are allowed.",
        )
    return normalized


def _record_boards_guardrail(
    project_key: str,
    *,
    duration_seconds: float,
    status: str,
    boards_count: int = 0,
) -> None:
    try:
        metrics.observe(
            "api_endpoint_duration_seconds",
            duration_seconds,
            labels={"endpoint": "jira_project_boards", "status": status},
        )
        if status != "ok":
            metrics.inc(
                "api_endpoint_error_total",
                labels={"endpoint": "jira_project_boards"},
            )
        if duration_seconds > JIRA_PROJECT_BOARDS_SLOW_THRESHOLD_SECONDS:
            metrics.inc(
                "api_endpoint_slow_total",
                labels={"endpoint": "jira_project_boards"},
            )
    except Exception:
        pass

    if status != "ok":
        logger.warning(
            "jira.project_boards.error project_key=%s duration=%.3f",
            project_key,
            duration_seconds,
        )
    elif duration_seconds > JIRA_PROJECT_BOARDS_SLOW_THRESHOLD_SECONDS:
        logger.warning(
            "jira.project_boards.slow project_key=%s boards=%s duration=%.3f threshold=%.3f",
            project_key,
            boards_count,
            duration_seconds,
            JIRA_PROJECT_BOARDS_SLOW_THRESHOLD_SECONDS,
        )


async def _call_jira(func, *args, **kwargs):
    """Run blocking Jira service calls off the event loop."""
    return await asyncio.to_thread(func, *args, **kwargs)


async def _connect_to_jira_impl(payload: JiraConnectRequest, db: AsyncSession) -> dict:
    """Shared connect+validate+save logic (auth is enforced by the endpoints)."""
    with handle_api_error(
        operation="connect_to_jira", exception_map={JiraAuthError: 401, JiraUnexpectedResponse: 502}
    ):
        normalized_base_url = _normalize_http_base_url(payload.base_url, "jira")
        resolved_use_pat = bool(payload.use_pat)
        connect_email = None if resolved_use_pat else (payload.email or None)

        logger.info(
            "Connecting to Jira: base_url=%s use_pat=%s has_email=%s",
            normalized_base_url,
            resolved_use_pat,
            bool(connect_email),
        )

        await _call_jira(
            jira_service.connect,
            normalized_base_url,
            connect_email,
            payload.api_token,
            use_pat=resolved_use_pat,
        )

        # Validate by calling /myself
        logger.info("Validating Jira connection...")
        await _call_jira(jira_service.validate)
        logger.info("Jira validation successful")

        if payload.save:
            # Persist credentials in DB
            result = await db.execute(
                select(IntegrationSetting).where(IntegrationSetting.kind == "jira")
            )
            row = result.scalar_one_or_none()
            async with transactional_session(db):
                if not row:
                    row = IntegrationSetting(kind="jira")
                    db.add(row)
                row.base_url = (
                    (jira_service.base_url or normalized_base_url).rstrip("/")
                    if (jira_service.base_url or normalized_base_url)
                    else None
                )
                row.email = None if resolved_use_pat else (payload.email or None)
                row.api_token = (
                    _encrypt_saved_token(payload.api_token) if payload.api_token else row.api_token
                )
            logger.info("Jira credentials saved to database")

        return {"status": "connected", "message": "Successfully connected to Jira"}


@router.post("/connect")
async def connect_to_jira(
    payload: JiraConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(
        require_integration_permission(Permissions.INTEGRATION_MANAGE)
    ),
):
    """Connect to Jira instance and validate credentials."""
    del current_user
    return await _connect_to_jira_impl(payload, db)


@router.get("/status")
async def jira_status(current_user: User | None = Depends(require_integration_access)):
    del current_user
    return jira_service.status()


@router.get("/projects")
async def list_accessible_projects(
    q: Optional[str] = None,
    current_user: User | None = Depends(require_integration_access),
):
    """List Jira projects accessible by current credentials (key, name, id)."""
    del current_user
    with handle_api_error(
        operation="list_accessible_projects",
        exception_map={JiraAuthError: 403, JiraUnexpectedResponse: 502},
    ):
        items = await _call_jira(jira_service.list_projects, query=q)
        return {"count": len(items), "projects": items}


@router.get("/projects/{project_key}/check")
async def check_project_key(
    project_key: str,
    current_user: User | None = Depends(require_integration_access),
):
    """Check whether a project key exists and is accessible."""
    del current_user
    try:
        data = await _call_jira(jira_service.get_project, project_key)
        return {"exists": True, "project": data}
    except Exception as e:
        return {"exists": False, "detail": str(e)}


@router.get("/projects/{project_key}/boards")
async def list_boards(
    project_key: str,
    current_user: User | None = Depends(require_integration_access),
):
    """List Agile boards for a given project key."""
    del current_user
    start = perf_counter()
    boards_count = 0
    status = "ok"

    try:
        boards = await _call_jira(jira_service.list_boards_for_project, project_key)
        boards_count = len(boards)
        return {"count": boards_count, "boards": boards}
    except Exception:
        status = "error"
        raise
    finally:
        _record_boards_guardrail(
            project_key,
            duration_seconds=perf_counter() - start,
            status=status,
            boards_count=boards_count,
        )


@router.get("/projects/{project_key}")
async def get_jira_project(
    project_key: str,
    current_user: User | None = Depends(require_integration_access),
):
    """Get project details from Jira"""
    del current_user
    with handle_api_error(
        operation="get_jira_project", status_code=404, context={"project_key": project_key}
    ):
        project = await _call_jira(jira_service.get_project, project_key)
        return project


@router.get("/projects/{project_key}/issues")
async def get_project_issues(
    project_key: str,
    max_results: int = 100,
    current_user: User | None = Depends(require_integration_access),
):
    """Get all issues for a project from Jira"""
    del current_user
    with handle_api_error(
        operation="get_project_issues",
        context={"project_key": project_key, "max_results": max_results},
        exception_map={JiraAuthError: 403, JiraUnexpectedResponse: 502},
    ):
        issues = await _call_jira(jira_service.get_project_issues, project_key, max_results)
        return {"total": len(issues), "issues": issues}


@router.post("/projects/{project_key}/sync")
async def sync_project_data(
    project_key: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(
        require_integration_permission(Permissions.PROJECT_UPDATE)
    ),
):
    """Sync project data from Jira to database.
    Be tolerant: if fetching project meta fails (e.g., restricted), still try to sync issues.
    """
    del current_user
    # Try fetching project info, but don't fail the whole sync if it errors
    logger = logging.getLogger(__name__)
    jira_project = None
    try:
        logger.info("Sync start project_key=%s", project_key)
        jira_project = await _call_jira(jira_service.get_project, project_key)
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

    reserved_sync_task = None
    created_new_lease = False
    async with transactional_session(db):
        reserved_sync_task, created_new_lease = await reserve_project_sync_task_lease(
            db,
            project_id=db_project.id,
            task_type="jira_sync",
            provider="jira",
            trigger="manual",
        )

    if not created_new_lease and reserved_sync_task is not None:
        logger.info(
            "Jira sync already running for project=%s existing_task_id=%s",
            project_key,
            reserved_sync_task.id,
        )
        return {
            "status": "syncing",
            "message": f"Jira sync is already running for project {project_key}",
            "project_id": db_project.id,
            "task_id": reserved_sync_task.id,
            "sync_task_id": reserved_sync_task.id,
            "sync_task_started_at": reserved_sync_task.started_at.isoformat()
            if reserved_sync_task.started_at
            else None,
            "method": "existing_running",
        }

    if reserved_sync_task is None:
        raise RuntimeError("Failed to reserve Jira sync task")

    # Dispatch sync via Celery (preferred) or FastAPI background task (fallback)
    task_id = None
    use_celery = getattr(settings, "CELERY_ENABLED", True)

    # Skip Celery in development if explicitly disabled
    if use_celery and getattr(settings, "is_development", False):
        if not getattr(settings, "CELERY_USE_IN_DEV", True):
            logger.info("Skipping Celery in development; using FastAPI background task")
            use_celery = False

    if use_celery:
        try:
            # Dispatch to Celery worker - non-blocking, doesn't hold event loop
            celery_result = sync_jira_project.delay(
                project_key,
                db_project.id,
                None,
                "manual",
                reserved_sync_task.id,
            )
            task_id = celery_result.id
            logger.info(
                "Jira sync dispatched to Celery: project=%s task_id=%s sync_task_id=%s",
                project_key,
                task_id,
                reserved_sync_task.id,
            )
            return {
                "status": "syncing",
                "message": f"Started Celery sync for project {project_key}",
                "project_id": db_project.id,
                "task_id": task_id,
                "sync_task_id": reserved_sync_task.id,
                "sync_task_started_at": reserved_sync_task.started_at.isoformat()
                if reserved_sync_task.started_at
                else None,
                "method": "celery",
            }
        except Exception as exc:
            logger.warning("Celery dispatch failed, falling back to FastAPI: %s", exc)
            use_celery = False

    # Fallback: FastAPI background task (still async, but in-process)
    logger.info("Dispatching Jira sync via FastAPI background task for project=%s", project_key)

    async def _async_sync_job(p_key: str, p_id: int, sync_task_id: int) -> None:
        """Wrapper to run async sync in FastAPI background task."""
        try:
            logger.info("FastAPI background task started for project=%s", p_key)
            await perform_project_sync(p_key, p_id, trigger="manual", sync_task_id=sync_task_id)
            logger.info("FastAPI background task completed for project=%s", p_key)
        except Exception as exc:
            logger.error(
                "FastAPI background task failed for project=%s: %s", p_key, exc, exc_info=True
            )

    background_tasks.add_task(_async_sync_job, project_key, db_project.id, reserved_sync_task.id)

    return {
        "status": "syncing",
        "message": f"Started FastAPI sync for project {project_key}",
        "project_id": db_project.id,
        "sync_task_id": reserved_sync_task.id,
        "sync_task_started_at": reserved_sync_task.started_at.isoformat()
        if reserved_sync_task.started_at
        else None,
        "method": "fastapi_background",
    }


@router.get("/sprints/{board_id}/active")
async def get_active_sprints(
    board_id: int,
    current_user: User | None = Depends(require_integration_access),
):
    """Get active sprints for a board"""
    del current_user
    with handle_api_error(operation="get_active_sprints", context={"board_id": board_id}):
        sprints = await _call_jira(jira_service.get_active_sprints, board_id)
        return {"total": len(sprints), "sprints": sprints}


@router.get("/issues/{issue_key}/worklogs")
async def get_issue_worklogs(
    issue_key: str,
    current_user: User | None = Depends(require_integration_access),
):
    """Get worklogs for an issue"""
    del current_user
    with handle_api_error(operation="get_issue_worklogs", context={"issue_key": issue_key}):
        worklogs = await _call_jira(jira_service.get_worklogs, issue_key)
        return {"total": len(worklogs), "worklogs": worklogs}


@router.post("/connect_pat")
async def connect_to_jira_pat(
    payload: JiraPatConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(
        require_integration_permission(Permissions.INTEGRATION_MANAGE)
    ),
):
    """Convenience endpoint to connect with PAT (Bearer) explicitly and persist credentials."""
    del current_user
    return await _connect_to_jira_impl(
        JiraConnectRequest(
            base_url=payload.base_url,
            api_token=payload.api_token,
            email=None,
            save=payload.save,
            use_pat=True,
        ),
        db,
    )


@router.get("/debug/{project_key}")
async def debug_jira_project(
    project_key: str,
    current_user: User | None = Depends(require_integration_access),
):
    """Debug endpoint to check Jira permissions and data availability for a project."""
    del current_user
    results: Dict[str, Any] = {"project_key": project_key, "checks": {}, "errors": []}

    # Check 1: Can we get the project?
    try:
        project = await _call_jira(jira_service.get_project, project_key)
        results["checks"]["project_access"] = {"success": True, "data": project}
    except Exception as e:
        results["checks"]["project_access"] = {"success": False, "error": str(e)}
        results["errors"].append(f"Cannot access project: {e}")

    # Check 2: Can we search for issues?
    try:
        issues = await _call_jira(jira_service.get_project_issues, project_key, 5)
        results["checks"]["issue_search"] = {
            "success": True,
            "count": len(issues),
            "sample": issues[:2] if issues else [],
        }
        if not issues:
            results["errors"].append(
                "No issues found - project may be empty or check 'Browse Projects' permission"
            )
    except Exception as e:
        results["checks"]["issue_search"] = {"success": False, "error": str(e)}
        results["errors"].append(f"Cannot search issues: {e}")

    # Check 3: Can we access boards?
    try:
        boards = await _call_jira(jira_service.list_boards_for_project, project_key)
        results["checks"]["board_access"] = {
            "success": True,
            "count": len(boards),
            "boards": [{"id": b.get("id"), "name": b.get("name")} for b in boards],
        }

        # Check 4: Can we get sprints from first board?
        if boards:
            first_board = boards[0]
            board_id_val = first_board.get("id")
            if board_id_val is None:
                results["checks"]["sprint_access"] = {"success": False, "error": "Board id missing"}
            else:
                try:
                    board_id_int = int(board_id_val)
                    sprints = await _call_jira(jira_service.list_sprints, board_id_int)
                    results["checks"]["sprint_access"] = {
                        "success": True,
                        "board_id": board_id_int,
                        "count": len(sprints),
                        "sample": [
                            {"id": s.get("id"), "name": s.get("name"), "state": s.get("state")}
                            for s in sprints[:3]
                        ],
                    }
                except Exception as e:
                    results["checks"]["sprint_access"] = {
                        "success": False,
                        "board_id": board_id_val,
                        "error": str(e),
                    }
                    results["errors"].append(f"Cannot access sprints: {e}")
        else:
            results["checks"]["sprint_access"] = {"success": False, "error": "No boards found"}
    except Exception as e:
        results["checks"]["board_access"] = {"success": False, "error": str(e)}
        results["errors"].append(f"Cannot access boards: {e}")

    # Summary
    results["summary"] = {"all_checks_passed": len(results["errors"]) == 0, "recommendations": []}

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
