"""RTM Matrix API - Requirements Traceability Matrix endpoints.

Provides:
- Sparse RTM matrix with server-side pagination
- Coverage analytics
- Saved matrix configurations (projections)
- Async exports
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ensure_project_access, get_current_user
from app.core.cache_enhanced import (
    CacheInvalidator,
    CacheTier,
    TraceabilityCacheKeys,
    get_enhanced_cache_service,
)
from app.core.config import settings
from app.core.database import get_db
from app.models import User
from app.models.traceability import ExportTask, MatrixConfig as MatrixConfigModel
from app.schemas.traceability import (
    CoverageAnalyticsResponse,
    ExportTaskCreate,
    ExportTaskStatus,
    MatrixConfig,
    MatrixConfigCreate,
    MatrixConfigUpdate,
    RTMFilters,
    RTMMatrixResponse,
    RTMPagination,
)
from app.services.analytics.coverage_analytics_service import get_coverage_analytics
from app.services.analytics.rtm_matrix_service import get_rtm_matrix
from app.utils import get_by_id_or_404, transactional_session

router = APIRouter()


# =============================================================================
# RTM Matrix Endpoints
# =============================================================================


@router.get("/rtm-matrix", response_model=RTMMatrixResponse)
async def get_rtm_matrix_endpoint(
    project_id: Optional[int] = Query(default=None, description="Filter by project"),
    row_types: Optional[str] = Query(
        default=None, description="Row artifact types (comma-separated)"
    ),
    col_types: Optional[str] = Query(
        default=None, description="Column artifact types (comma-separated)"
    ),
    row_statuses: Optional[str] = Query(
        default=None, description="Filter rows by status (comma-separated)"
    ),
    col_statuses: Optional[str] = Query(
        default=None, description="Filter columns by status (comma-separated)"
    ),
    link_types: Optional[str] = Query(
        default=None, description="Link types to include (comma-separated)"
    ),
    min_confidence: float = Query(
        default=0.0, ge=0.0, le=1.0, description="Minimum confidence threshold"
    ),
    search_query: Optional[str] = Query(
        default=None, description="Text search in artifact titles"
    ),
    direction: str = Query(
        default="both", description="Link direction: outgoing, incoming, or both"
    ),
    include_orphans: bool = Query(
        default=False, description="Include artifacts without links"
    ),
    row_skip: int = Query(default=0, ge=0, description="Skip N rows"),
    row_limit: int = Query(default=50, ge=1, le=500, description="Max rows to return"),
    col_skip: int = Query(default=0, ge=0, description="Skip N columns"),
    col_limit: int = Query(default=50, ge=1, le=500, description="Max columns to return"),
    include_link_details: bool = Query(
        default=False, description="Include detailed link info in cells"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get RTM matrix with server-side pagination and filtering.

    The matrix shows relationships between row artifacts (e.g., requirements)
    and column artifacts (e.g., test cases, tasks).

    Each cell indicates whether links exist between the row and column artifacts.
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Parse comma-separated parameters
    row_types_list = row_types.split(",") if row_types else None
    col_types_list = col_types.split(",") if col_types else None
    row_statuses_list = row_statuses.split(",") if row_statuses else None
    col_statuses_list = col_statuses.split(",") if col_statuses else None
    link_types_list = link_types.split(",") if link_types else None

    # Check cache with ALL filter parameters to prevent collisions
    cache_key = TraceabilityCacheKeys.rtm_matrix(
        project_id=project_id,
        row_types=row_types,
        col_types=col_types,
        row_skip=row_skip,
        row_limit=row_limit,
        col_skip=col_skip,
        col_limit=col_limit,
        row_statuses=row_statuses,
        col_statuses=col_statuses,
        link_types=link_types,
        min_confidence=min_confidence,
        direction=direction,
        search_query=search_query,
        include_orphans=include_orphans,
    )
    cache_service = get_enhanced_cache_service()

    if getattr(settings, "ENABLE_MATRIX_CACHE", True):
        cached = await cache_service.get(cache_key, CacheTier.WARM)
        if cached is not None:
            return cached

    # Get matrix from service
    result = await get_rtm_matrix(
        db=db,
        project_id=project_id,
        row_types=row_types_list,
        col_types=col_types_list,
        row_statuses=row_statuses_list,
        col_statuses=col_statuses_list,
        link_types=link_types_list,
        min_confidence=min_confidence,
        search_query=search_query,
        direction=direction,
        include_orphans=include_orphans,
        row_skip=row_skip,
        row_limit=row_limit,
        col_skip=col_skip,
        col_limit=col_limit,
        include_link_details=include_link_details,
    )

    # Cache result
    if getattr(settings, "ENABLE_MATRIX_CACHE", True):
        await cache_service.set(cache_key, result, CacheTier.WARM)

    return result


@router.post("/rtm-matrix/query", response_model=RTMMatrixResponse)
async def query_rtm_matrix_endpoint(
    filters: RTMFilters,
    pagination: Optional[RTMPagination] = None,
    include_link_details: bool = False,
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Query RTM matrix with complex filters via POST body.

    Use this endpoint when you need to pass complex filter configurations.
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    pag = pagination or RTMPagination()

    result = await get_rtm_matrix(
        db=db,
        project_id=project_id,
        row_types=filters.row_types,
        col_types=filters.col_types,
        row_statuses=filters.row_statuses,
        col_statuses=filters.col_statuses,
        link_types=filters.link_types,
        min_confidence=filters.min_confidence,
        search_query=filters.search_query,
        direction=filters.direction,
        include_orphans=filters.include_orphans,
        row_skip=pag.row_skip,
        row_limit=pag.row_limit,
        col_skip=pag.col_skip,
        col_limit=pag.col_limit,
        include_link_details=include_link_details,
    )

    return result


# =============================================================================
# Coverage Analytics Endpoints
# =============================================================================


@router.get("/coverage-analytics")
async def get_coverage_analytics_endpoint(
    project_id: Optional[int] = Query(default=None, description="Filter by project"),
    artifact_types: Optional[str] = Query(
        default=None, description="Artifact types to analyze (comma-separated)"
    ),
    include_trends: bool = Query(
        default=False, description="Include historical trend data"
    ),
    trend_days: int = Query(
        default=30, ge=1, le=365, description="Days of trend data to include"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get comprehensive coverage analytics.

    Includes:
    - Coverage statistics by artifact type
    - List of uncovered requirements
    - Gap analysis
    - Coverage trends over time (optional)
    - Quality gate evaluation
    """
    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)

    # Parse artifact types
    types_list = artifact_types.split(",") if artifact_types else None

    # Check cache with ALL parameters to prevent collisions
    cache_key = TraceabilityCacheKeys.coverage_analytics(
        project_id=project_id,
        include_trends=include_trends,
        artifact_types=artifact_types,
        trend_days=trend_days,
    )
    cache_service = get_enhanced_cache_service()

    if getattr(settings, "ENABLE_MATRIX_CACHE", True):
        cached = await cache_service.get(cache_key, CacheTier.COLD)
        if cached is not None:
            return cached

    # Get analytics from service
    result = await get_coverage_analytics(
        db=db,
        project_id=project_id,
        artifact_types=types_list,
        include_trends=include_trends,
        trend_days=trend_days,
    )

    # Cache result
    if getattr(settings, "ENABLE_MATRIX_CACHE", True):
        await cache_service.set(cache_key, result, CacheTier.COLD)

    return result


# =============================================================================
# Matrix Config (Saved Projections) Endpoints
# =============================================================================


@router.get("/matrix-configs", response_model=List[MatrixConfig])
async def list_matrix_configs(
    project_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List saved matrix configurations for a project."""
    stmt = select(MatrixConfigModel).order_by(MatrixConfigModel.created_at.desc())

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(MatrixConfigModel.project_id == project_id)

    result = await db.execute(stmt)
    configs = result.scalars().all()

    # Convert JSON fields to Pydantic models
    return [
        MatrixConfig(
            id=c.id,
            project_id=c.project_id,
            created_by_id=c.created_by_id,
            name=c.name,
            description=c.description,
            filters=RTMFilters(**c.filters_json) if c.filters_json else None,
            pagination=RTMPagination(**c.pagination_json) if c.pagination_json else None,
            display_options=c.display_options_json,
            is_default=c.is_default,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in configs
    ]


@router.post("/matrix-configs", response_model=MatrixConfig)
async def create_matrix_config(
    payload: MatrixConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new matrix configuration."""
    if payload.project_id is not None:
        await ensure_project_access(payload.project_id, db, current_user)

    # If setting as default, unset other defaults for this project
    if payload.is_default and payload.project_id is not None:
        async with transactional_session(db):
            existing_defaults = await db.execute(
                select(MatrixConfigModel).where(
                    MatrixConfigModel.project_id == payload.project_id,
                    MatrixConfigModel.is_default.is_(True),
                )
            )
            for config in existing_defaults.scalars().all():
                config.is_default = False

    config = MatrixConfigModel(
        project_id=payload.project_id,
        created_by_id=current_user.id,
        name=payload.name,
        description=payload.description,
        filters_json=payload.filters.model_dump() if payload.filters else None,
        pagination_json=payload.pagination.model_dump() if payload.pagination else None,
        display_options_json=payload.display_options,
        is_default=payload.is_default,
    )

    async with transactional_session(db):
        db.add(config)

    await db.refresh(config)

    # Invalidate cache
    await CacheInvalidator.on_artifact_link_change(payload.project_id)

    return MatrixConfig(
        id=config.id,
        project_id=config.project_id,
        created_by_id=config.created_by_id,
        name=config.name,
        description=config.description,
        filters=RTMFilters(**config.filters_json) if config.filters_json else None,
        pagination=RTMPagination(**config.pagination_json) if config.pagination_json else None,
        display_options=config.display_options_json,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("/matrix-configs/{config_id}", response_model=MatrixConfig)
async def get_matrix_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific matrix configuration."""
    config = await get_by_id_or_404(db, MatrixConfigModel, config_id)

    if config.project_id is not None:
        await ensure_project_access(config.project_id, db, current_user)

    return MatrixConfig(
        id=config.id,
        project_id=config.project_id,
        created_by_id=config.created_by_id,
        name=config.name,
        description=config.description,
        filters=RTMFilters(**config.filters_json) if config.filters_json else None,
        pagination=RTMPagination(**config.pagination_json) if config.pagination_json else None,
        display_options=config.display_options_json,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.patch("/matrix-configs/{config_id}", response_model=MatrixConfig)
async def update_matrix_config(
    config_id: int,
    payload: MatrixConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a matrix configuration."""
    config = await get_by_id_or_404(db, MatrixConfigModel, config_id)

    if config.project_id is not None:
        await ensure_project_access(config.project_id, db, current_user)

    # If setting as default, unset other defaults
    if payload.is_default and config.project_id is not None:
        async with transactional_session(db):
            existing_defaults = await db.execute(
                select(MatrixConfigModel).where(
                    MatrixConfigModel.project_id == config.project_id,
                    MatrixConfigModel.is_default.is_(True),
                    MatrixConfigModel.id != config_id,
                )
            )
            for c in existing_defaults.scalars().all():
                c.is_default = False

    async with transactional_session(db):
        if payload.name is not None:
            config.name = payload.name
        if payload.description is not None:
            config.description = payload.description
        if payload.filters is not None:
            config.filters_json = payload.filters.model_dump()
        if payload.pagination is not None:
            config.pagination_json = payload.pagination.model_dump()
        if payload.display_options is not None:
            config.display_options_json = payload.display_options
        if payload.is_default is not None:
            config.is_default = payload.is_default

    await db.refresh(config)

    return MatrixConfig(
        id=config.id,
        project_id=config.project_id,
        created_by_id=config.created_by_id,
        name=config.name,
        description=config.description,
        filters=RTMFilters(**config.filters_json) if config.filters_json else None,
        pagination=RTMPagination(**config.pagination_json) if config.pagination_json else None,
        display_options=config.display_options_json,
        is_default=config.is_default,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.delete("/matrix-configs/{config_id}")
async def delete_matrix_config(
    config_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a matrix configuration."""
    config = await get_by_id_or_404(db, MatrixConfigModel, config_id)

    if config.project_id is not None:
        await ensure_project_access(config.project_id, db, current_user)

    async with transactional_session(db):
        await db.delete(config)

    return {"status": "deleted", "id": config_id}


@router.get("/matrix-configs/{config_id}/apply", response_model=RTMMatrixResponse)
async def apply_matrix_config(
    config_id: int,
    include_link_details: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Apply a saved matrix configuration and return the matrix."""
    config = await get_by_id_or_404(db, MatrixConfigModel, config_id)

    if config.project_id is not None:
        await ensure_project_access(config.project_id, db, current_user)

    filters = RTMFilters(**config.filters_json) if config.filters_json else RTMFilters()
    pagination = RTMPagination(**config.pagination_json) if config.pagination_json else RTMPagination()

    result = await get_rtm_matrix(
        db=db,
        project_id=config.project_id,
        row_types=filters.row_types,
        col_types=filters.col_types,
        row_statuses=filters.row_statuses,
        col_statuses=filters.col_statuses,
        link_types=filters.link_types,
        min_confidence=filters.min_confidence,
        search_query=filters.search_query,
        direction=filters.direction,
        include_orphans=filters.include_orphans,
        row_skip=pagination.row_skip,
        row_limit=pagination.row_limit,
        col_skip=pagination.col_skip,
        col_limit=pagination.col_limit,
        include_link_details=include_link_details,
    )

    return result


# =============================================================================
# Export Task Endpoints
# =============================================================================


@router.post("/exports", response_model=ExportTaskStatus)
async def create_export_task(
    payload: ExportTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create an async export task for RTM matrix.

    Supported formats: csv, xlsx, pdf

    The export will run in the background. Use GET /exports/{task_id}
    to check status and get download URL when complete.
    """
    await ensure_project_access(payload.project_id, db, current_user)

    # Validate format
    supported_formats = ["csv", "xlsx", "pdf"]
    if payload.format not in supported_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {payload.format}. Supported: {supported_formats}",
        )

    # Generate unique task ID
    task_id = str(uuid.uuid4())

    # Create export task record
    export_task = ExportTask(
        task_id=task_id,
        project_id=payload.project_id,
        created_by_id=current_user.id,
        export_type="matrix",
        format=payload.format,
        status="pending",
        config_json={
            "matrix_config_id": payload.matrix_config_id,
            "filters": payload.filters.model_dump() if payload.filters else None,
            "include_details": payload.include_details,
        },
    )

    async with transactional_session(db):
        db.add(export_task)

    await db.refresh(export_task)

    # Trigger async export via Celery if enabled
    if settings.CELERY_ENABLED:
        from app.tasks.export_tasks import export_matrix_task

        # Generate channel ID for SSE updates
        channel_id = f"{current_user.id}_{task_id[:8]}"

        export_matrix_task.delay(
            export_task_id=task_id,
            project_id=payload.project_id,
            format=payload.format,
            filters=payload.filters.model_dump() if payload.filters else None,
            include_details=payload.include_details,
            channel_id=channel_id,
        )
    else:
        # Run synchronously for development without Celery
        await _run_sync_export(
            db, export_task, payload.project_id, payload.format,
            payload.filters.model_dump() if payload.filters else None,
            payload.include_details,
        )
        await db.refresh(export_task)

    return ExportTaskStatus(
        task_id=task_id,
        status=export_task.status,
        progress_pct=export_task.progress_pct,
        download_url=(
            f"/api/v1/traceability/exports/{task_id}/download"
            if export_task.status == "completed" else None
        ),
        error_message=export_task.error_message,
        created_at=export_task.created_at,
        completed_at=export_task.completed_at,
    )


@router.get("/exports/{task_id}", response_model=ExportTaskStatus)
async def get_export_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the status of an export task."""
    stmt = select(ExportTask).where(ExportTask.task_id == task_id)
    result = await db.execute(stmt)
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    if export_task.project_id is not None:
        await ensure_project_access(export_task.project_id, db, current_user)

    # Generate download URL if completed
    download_url = None
    if export_task.status == "completed" and export_task.file_path:
        download_url = f"/api/v1/traceability/exports/{task_id}/download"

    return ExportTaskStatus(
        task_id=task_id,
        status=export_task.status,
        progress_pct=export_task.progress_pct,
        download_url=download_url,
        error_message=export_task.error_message,
        created_at=export_task.created_at,
        completed_at=export_task.completed_at,
    )


@router.get("/exports")
async def list_export_tasks(
    project_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List export tasks for a project."""
    stmt = select(ExportTask).order_by(ExportTask.created_at.desc()).limit(limit)

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(ExportTask.project_id == project_id)

    if status:
        stmt = stmt.where(ExportTask.status == status)

    result = await db.execute(stmt)
    tasks = result.scalars().all()

    return [
        ExportTaskStatus(
            task_id=t.task_id,
            status=t.status,
            progress_pct=t.progress_pct,
            download_url=f"/api/v1/traceability/exports/{t.task_id}/download"
            if t.status == "completed" and t.file_path
            else None,
            error_message=t.error_message,
            created_at=t.created_at,
            completed_at=t.completed_at,
        )
        for t in tasks
    ]


@router.get("/exports/{task_id}/download")
async def download_export(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the completed export file."""
    stmt = select(ExportTask).where(ExportTask.task_id == task_id)
    result = await db.execute(stmt)
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    if export_task.project_id is not None:
        await ensure_project_access(export_task.project_id, db, current_user)

    if export_task.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Export not ready. Status: {export_task.status}",
        )

    if not export_task.file_path or not os.path.exists(export_task.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")

    # Determine content type and filename
    if export_task.format == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"traceability_matrix_{task_id[:8]}.xlsx"
    elif export_task.format == "pdf":
        media_type = "application/pdf"
        filename = f"traceability_matrix_{task_id[:8]}.pdf"
    else:  # csv
        media_type = "text/csv"
        filename = f"traceability_matrix_{task_id[:8]}.csv"

    return FileResponse(
        path=export_task.file_path,
        media_type=media_type,
        filename=filename,
    )


@router.delete("/exports/{task_id}")
async def delete_export(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an export task and its file."""
    stmt = select(ExportTask).where(ExportTask.task_id == task_id)
    result = await db.execute(stmt)
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    # Check access - only owner can delete
    if export_task.created_by_id != current_user.id:
        if export_task.project_id:
            await ensure_project_access(export_task.project_id, db, current_user)
        else:
            raise HTTPException(status_code=403, detail="Not authorized")

    # Delete file if exists
    if export_task.file_path and os.path.exists(export_task.file_path):
        try:
            os.remove(export_task.file_path)
        except OSError:
            pass  # Ignore file deletion errors

    async with transactional_session(db):
        await db.delete(export_task)

    return {"status": "deleted", "task_id": task_id}


# =============================================================================
# Helper Functions
# =============================================================================


async def _run_sync_export(
    db: AsyncSession,
    export_task: ExportTask,
    project_id: int,
    format: str,
    filters: Optional[Dict[str, Any]],
    include_details: bool,
) -> None:
    """Run export synchronously for development without Celery.

    Uses export_service.process_export_task to ensure consistency with
    RTM matrix data (same filters, direction, and data source).
    """
    from app.services.analytics.export_service import process_export_task

    try:
        # Use the export service which properly applies all filters via get_rtm_matrix
        result = await process_export_task(db, export_task.task_id)

        # Allowlist: only "completed" is success, any other status is failure
        if result.get("status") != "completed":
            raise HTTPException(
                status_code=500,
                detail=f"Export failed: {result.get('message', 'Unknown error')}"
            )

    except HTTPException:
        raise
    except Exception as e:
        export_task.status = "failed"
        export_task.error_message = str(e)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")
