"""Export endpoints for traceability matrix and related data.

Provides async export functionality with progress tracking and file downloads.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.api.deps import get_current_user, ensure_project_access
from app.models import User
from app.models.traceability import ExportTask as ExportTaskModel
from app.schemas.traceability import ExportTaskCreate, ExportTaskStatus
from app.utils import transactional_session

router = APIRouter()


@router.post("/exports/matrix", response_model=ExportTaskStatus)
async def create_matrix_export(
    payload: ExportTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create an async export task for the traceability matrix.

    Returns immediately with a task_id that can be used to track progress
    and download the file when complete.
    """
    # Validate project access
    await ensure_project_access(payload.project_id, db, current_user)

    # Validate format
    allowed_formats = ["xlsx", "csv"]
    if payload.format not in allowed_formats:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid format. Allowed: {allowed_formats}",
        )

    # Generate unique task ID
    task_id = str(uuid.uuid4())

    # Create export task record
    export_task = ExportTaskModel(
        task_id=task_id,
        project_id=payload.project_id,
        created_by_id=current_user.id,
        export_type="matrix",
        format=payload.format,
        status="pending",
        progress_pct=0.0,
        config_json={
            "filters": payload.filters.model_dump() if payload.filters else None,
            "include_details": payload.include_details,
            "matrix_config_id": payload.matrix_config_id,
        },
    )

    async with transactional_session(db):
        db.add(export_task)

    await db.refresh(export_task)

    # Queue Celery task if enabled
    if settings.CELERY_ENABLED:
        from app.tasks.export_tasks import export_matrix_task

        # Generate channel ID for SSE
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
        from app.tasks.export_tasks import _async_export_matrix
        import asyncio

        # Update status to processing
        export_task.status = "processing"
        export_task.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Run export inline
            result = await _run_sync_export(
                task_id,
                payload.project_id,
                payload.format,
                payload.filters.model_dump() if payload.filters else None,
                payload.include_details,
            )

            # Update with result
            export_task.status = "completed"
            export_task.file_path = result["file_path"]
            export_task.file_size_bytes = result["file_size_bytes"]
            export_task.progress_pct = 100.0
            export_task.completed_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception as e:
            export_task.status = "failed"
            export_task.error_message = str(e)
            await db.commit()
            raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    return ExportTaskStatus(
        task_id=task_id,
        status=export_task.status,
        progress_pct=export_task.progress_pct,
        download_url=None,
        error_message=None,
        created_at=export_task.created_at,
        completed_at=export_task.completed_at,
    )


async def _run_sync_export(
    task_id: str,
    project_id: int,
    format: str,
    filters: Optional[dict],
    include_details: bool,
) -> dict:
    """Run export synchronously (for non-Celery mode)."""
    from app.core.database import AsyncSessionLocal
    from app.models.traceability import Artifact, ArtifactLink, ExportTask
    from app.tasks.export_tasks import (
        _build_matrix_data,
        _generate_xlsx,
        _generate_csv,
        _create_empty_export,
    )

    async with AsyncSessionLocal() as db:
        # Build query
        artifacts_stmt = select(Artifact)
        if project_id is not None:
            artifacts_stmt = artifacts_stmt.where(Artifact.project_id == project_id)

        if filters:
            if filters.get("row_types"):
                artifacts_stmt = artifacts_stmt.where(
                    Artifact.type.in_(filters["row_types"])
                )

        res = await db.execute(artifacts_stmt)
        artifacts = res.scalars().all()

        if not artifacts:
            file_path = await _create_empty_export(task_id, format)
            return {"file_path": file_path, "file_size_bytes": 0}

        # Fetch links
        artifact_ids = [art.id for art in artifacts]
        link_stmt = select(ArtifactLink).where(
            ArtifactLink.from_artifact_id.in_(artifact_ids)
        )
        if filters and filters.get("link_types"):
            link_stmt = link_stmt.where(
                ArtifactLink.link_type.in_(filters["link_types"])
            )

        res_links = await db.execute(link_stmt)
        links = res_links.scalars().all()

        # Build and generate
        export_data = _build_matrix_data(artifacts, links, include_details)

        if format == "xlsx":
            file_path = await _generate_xlsx(task_id, export_data)
        else:
            file_path = await _generate_csv(task_id, export_data)

        file_size = os.path.getsize(file_path)
        return {"file_path": file_path, "file_size_bytes": file_size}


@router.get("/exports/{task_id}/status", response_model=ExportTaskStatus)
async def get_export_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the status of an export task."""
    result = await db.execute(
        select(ExportTaskModel).where(ExportTaskModel.task_id == task_id)
    )
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    # Check access
    if export_task.project_id:
        await ensure_project_access(export_task.project_id, db, current_user)

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


@router.get("/exports/{task_id}/download")
async def download_export(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download the completed export file."""
    result = await db.execute(
        select(ExportTaskModel).where(ExportTaskModel.task_id == task_id)
    )
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    # Check access
    if export_task.project_id:
        await ensure_project_access(export_task.project_id, db, current_user)

    if export_task.status != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Export not ready. Status: {export_task.status}",
        )

    if not export_task.file_path or not os.path.exists(export_task.file_path):
        raise HTTPException(status_code=404, detail="Export file not found")

    # Determine content type
    if export_task.format == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"traceability_matrix_{task_id[:8]}.xlsx"
    elif export_task.format == "pdf":
        media_type = "application/pdf"
        filename = f"traceability_matrix_{task_id[:8]}.pdf"
    else:
        media_type = "text/csv"
        filename = f"traceability_matrix_{task_id[:8]}.csv"

    return FileResponse(
        path=export_task.file_path,
        media_type=media_type,
        filename=filename,
    )


@router.get("/exports", response_model=List[ExportTaskStatus])
async def list_exports(
    project_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List export tasks for the current user or project."""
    stmt = select(ExportTaskModel).order_by(desc(ExportTaskModel.created_at))

    if project_id is not None:
        await ensure_project_access(project_id, db, current_user)
        stmt = stmt.where(ExportTaskModel.project_id == project_id)
    else:
        # Filter by user's exports only
        stmt = stmt.where(ExportTaskModel.created_by_id == current_user.id)

    if status:
        stmt = stmt.where(ExportTaskModel.status == status)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    exports = result.scalars().all()

    return [
        ExportTaskStatus(
            task_id=exp.task_id,
            status=exp.status,
            progress_pct=exp.progress_pct,
            download_url=(
                f"/api/v1/traceability/exports/{exp.task_id}/download"
                if exp.status == "completed" and exp.file_path
                else None
            ),
            error_message=exp.error_message,
            created_at=exp.created_at,
            completed_at=exp.completed_at,
        )
        for exp in exports
    ]


@router.delete("/exports/{task_id}")
async def delete_export(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an export task and its file."""
    result = await db.execute(
        select(ExportTaskModel).where(ExportTaskModel.task_id == task_id)
    )
    export_task = result.scalar_one_or_none()

    if not export_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    # Check access - only owner or admin can delete
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

    # Delete record
    async with transactional_session(db):
        await db.delete(export_task)

    return {"status": "deleted", "task_id": task_id}
