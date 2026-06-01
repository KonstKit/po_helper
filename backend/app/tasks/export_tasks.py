"""
Celery tasks for traceability export operations.
Provides background processing with progress tracking for matrix and graph exports.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, cast

from celery import Task
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import update

from app.core.cache import redis_client as _redis_client
from app.core.celery_async_runner import run_async
from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.traceability import Artifact, ArtifactLink, ExportTask

logger = logging.getLogger(__name__)


class ExportBaseTask(Task):
    """Base task class with progress tracking for exports."""

    def __init__(self) -> None:
        super().__init__()
        self.total_items = 0
        self.processed_items = 0
        self.channel_id: Optional[str] = None
        self.export_task_id: Optional[str] = None

    def update_progress(self, message: str, percent: Optional[int] = None) -> None:
        """Update task progress and send SSE update if channel is configured."""
        effective_percent = (
            percent
            if percent is not None
            else int((self.processed_items / max(self.total_items, 1)) * 100)
        )

        # Update Celery task state
        self.update_state(
            state="PROGRESS",
            meta={
                "current": self.processed_items,
                "total": self.total_items,
                "percent": effective_percent,
                "message": message,
            },
        )

        # Send SSE update if channel is configured
        if self.channel_id and redis_client:
            try:
                redis_client.publish(
                    f"export_{self.channel_id}",
                    json.dumps(
                        {
                            "type": "progress",
                            "percent": effective_percent,
                            "message": message,
                            "processed": self.processed_items,
                            "total": self.total_items,
                            "task_id": self.export_task_id,
                        }
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to send SSE update: {e}")


@celery_app.task(
    bind=True,
    base=ExportBaseTask,
    name="traceability.export_matrix",
    max_retries=2,
    soft_time_limit=600,  # 10 minutes soft limit
    time_limit=900,  # 15 minutes hard limit
    acks_late=True,
    reject_on_worker_lost=True,
)
def export_matrix_task(
    self: ExportBaseTask,
    export_task_id: str,
    project_id: Optional[int] = None,
    format: str = "xlsx",
    filters: Optional[Dict[str, Any]] = None,
    include_details: bool = False,
    channel_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export traceability matrix to file (xlsx/csv).

    Args:
        export_task_id: ID of the ExportTask record
        project_id: Project to export
        format: Export format (xlsx, csv)
        filters: Optional filters to apply
        include_details: Include detailed link information
        channel_id: Optional SSE channel for real-time updates

    Returns:
        Dictionary with export result including file path
    """
    self.channel_id = channel_id
    self.export_task_id = export_task_id

    try:
        self.update_progress("Starting matrix export...", 5)

        # Run async export in sync context
        result = run_async(
            _async_export_matrix(
                self,
                export_task_id,
                project_id,
                format,
                filters,
                include_details,
            )
        )

        # Send completion notification
        if channel_id and redis_client:
            redis_client.publish(
                f"export_{channel_id}",
                json.dumps(
                    {
                        "type": "complete",
                        "percent": 100,
                        "message": "Export complete! File ready for download.",
                        "task_id": export_task_id,
                        "download_url": f"/api/v1/traceability/exports/{export_task_id}/download",
                        "file_size": result.get("file_size_bytes"),
                    }
                ),
            )

        return result

    except Exception as exc:
        logger.error(f"Export task failed: {exc}")

        # Update ExportTask status to failed
        try:
            run_async(_update_export_status(export_task_id, "failed", str(exc)))
        except Exception as update_exc:
            # CRITICAL: Status update failed - task will appear stuck in DB
            logger.critical(
                f"CRITICAL: Failed to update export status to 'failed' for task {export_task_id}: {update_exc}. "
                f"Original error: {exc}. Manual DB cleanup may be required."
            )

        # Send error notification
        if channel_id and redis_client:
            redis_client.publish(
                f"export_{channel_id}",
                json.dumps(
                    {
                        "type": "error",
                        "message": str(exc),
                        "task_id": export_task_id,
                    }
                ),
            )
        raise


async def _async_export_matrix(
    task: ExportBaseTask,
    export_task_id: str,
    project_id: Optional[int],
    format: str,
    filters: Optional[Dict[str, Any]],
    include_details: bool,
) -> Dict[str, Any]:
    """
    Async implementation of matrix export.

    Delegates to export_service.process_export_task which:
    - Reads full config (including matrix_config_id, all filters) from ExportTask.config_json
    - Uses get_rtm_matrix with all filter options (row/col types, statuses, search_query, direction, etc.)
    - Ensures consistency between sync and async export paths
    """
    from app.services.analytics.export_service import process_export_task

    async with AsyncSessionLocal() as db:
        task.update_progress("Processing export via RTM matrix service...", 10)

        # Use the unified export service which reads config from ExportTask.config_json
        # This ensures all filters (including col_types, search_query, direction, etc.) are applied
        result = await process_export_task(db, export_task_id)

        # Allowlist: only "completed" is success, any other status is failure
        if result.get("status") != "completed":
            raise RuntimeError(result.get("message", "Export failed"))

        task.update_progress("Export completed", 100)

        return {
            "file_path": result.get("file_path", ""),
            "file_size_bytes": result.get("file_size", 0),
        }


def _build_matrix_data(
    artifacts: List[Artifact],
    links: List[ArtifactLink],
    include_details: bool,
) -> Dict[str, Any]:
    """Build structured data for export."""

    # Group artifacts by type
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    artifact_map: Dict[int, Dict[str, Any]] = {}

    for art in artifacts:
        art_data = {
            "id": art.id,
            "type": art.type,
            "external_id": art.external_id,
            "display_key": art.display_key or art.external_id,
            "title": art.title or "",
            "status": art.status or "",
            "url": art.url or "",
            "links": [],
            "link_count": 0,
        }
        by_type.setdefault(art.type, []).append(art_data)
        artifact_map[art.id] = art_data

    # Map links to artifacts
    for link in links:
        from_art = artifact_map.get(link.from_artifact_id)
        if from_art:
            link_data = {
                "to_id": link.to_artifact_id,
                "link_type": link.link_type,
                "confidence": link.confidence,
            }
            from_art["links"].append(link_data)
            from_art["link_count"] += 1

    # Calculate coverage stats
    stats: Dict[str, Dict[str, Any]] = {}
    for art_type, arts in by_type.items():
        linked = sum(1 for a in arts if a["link_count"] > 0)
        total = len(arts)
        stats[art_type] = {
            "total": total,
            "linked": linked,
            "unlinked": total - linked,
            "coverage_pct": (linked / total * 100) if total > 0 else 0.0,
        }

    return {
        "by_type": by_type,
        "stats": stats,
        "include_details": include_details,
        "total_artifacts": len(artifacts),
        "total_links": len(links),
    }


async def _generate_xlsx(
    export_task_id: str,
    data: Dict[str, Any],
) -> str:
    """Generate Excel file with matrix data."""

    wb = Workbook()

    # Summary sheet
    ws_summary = wb.active
    ws_summary.title = "Summary"

    # Header styling
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="0B4F6C", end_color="0B4F6C", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Summary header
    summary_headers = ["Artifact Type", "Total", "Linked", "Unlinked", "Coverage %"]
    for col, header in enumerate(summary_headers, 1):
        cell = ws_summary.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")

    # Summary data
    row = 2
    for art_type, stat in data["stats"].items():
        ws_summary.cell(row=row, column=1, value=art_type).border = thin_border
        ws_summary.cell(row=row, column=2, value=stat["total"]).border = thin_border
        ws_summary.cell(row=row, column=3, value=stat["linked"]).border = thin_border
        ws_summary.cell(row=row, column=4, value=stat["unlinked"]).border = thin_border
        coverage_cell = ws_summary.cell(row=row, column=5, value=f"{stat['coverage_pct']:.1f}%")
        coverage_cell.border = thin_border
        coverage_cell.alignment = Alignment(horizontal="right")
        row += 1

    # Totals row
    ws_summary.cell(row=row, column=1, value="TOTAL").font = Font(bold=True)
    ws_summary.cell(row=row, column=2, value=data["total_artifacts"]).font = Font(bold=True)

    # Auto-width columns
    for col in range(1, 6):
        ws_summary.column_dimensions[get_column_letter(col)].width = 15

    # Artifacts sheet for each type
    for art_type, artifacts in data["by_type"].items():
        ws = wb.create_sheet(title=art_type[:31])  # Excel limits to 31 chars

        headers = ["ID", "Key", "Title", "Status", "Links", "URL"]
        if data["include_details"]:
            headers.extend(["Link Types", "Avg Confidence"])

        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border

        for row_idx, art in enumerate(artifacts, 2):
            ws.cell(row=row_idx, column=1, value=art["id"])
            ws.cell(row=row_idx, column=2, value=art["display_key"])
            ws.cell(row=row_idx, column=3, value=art["title"][:500] if art["title"] else "")
            ws.cell(row=row_idx, column=4, value=art["status"])
            ws.cell(row=row_idx, column=5, value=art["link_count"])
            ws.cell(row=row_idx, column=6, value=art["url"])

            if data["include_details"] and art["links"]:
                link_types = ", ".join(set(link_item["link_type"] for link_item in art["links"]))
                avg_conf = sum(link_item["confidence"] or 0 for link_item in art["links"]) / len(
                    art["links"]
                )
                ws.cell(row=row_idx, column=7, value=link_types)
                ws.cell(row=row_idx, column=8, value=f"{avg_conf:.2f}")

        # Auto-width
        ws.column_dimensions["A"].width = 10
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 50
        ws.column_dimensions["D"].width = 15
        ws.column_dimensions["E"].width = 10
        ws.column_dimensions["F"].width = 40

    # Save file
    exports_dir = Path(settings.EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    file_path = exports_dir / f"matrix_{export_task_id}.xlsx"

    wb.save(str(file_path))
    return str(file_path)


async def _generate_csv(
    export_task_id: str,
    data: Dict[str, Any],
) -> str:
    """Generate CSV file with matrix data."""
    import csv

    exports_dir = Path(settings.EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)
    file_path = exports_dir / f"matrix_{export_task_id}.csv"

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header
        headers = ["Type", "ID", "Key", "Title", "Status", "Link Count", "URL"]
        if data["include_details"]:
            headers.extend(["Link Types", "Avg Confidence"])
        writer.writerow(headers)

        # Data
        for art_type, artifacts in data["by_type"].items():
            for art in artifacts:
                row = [
                    art_type,
                    art["id"],
                    art["display_key"],
                    art["title"],
                    art["status"],
                    art["link_count"],
                    art["url"],
                ]
                if data["include_details"] and art["links"]:
                    link_types = "|".join(set(link_item["link_type"] for link_item in art["links"]))
                    avg_conf = sum(
                        link_item["confidence"] or 0 for link_item in art["links"]
                    ) / len(art["links"])
                    row.extend([link_types, f"{avg_conf:.2f}"])
                elif data["include_details"]:
                    row.extend(["", ""])
                writer.writerow(row)

    return str(file_path)


async def _create_empty_export(export_task_id: str, format: str) -> str:
    """Create an empty export file."""
    exports_dir = Path(settings.EXPORTS_DIR)
    exports_dir.mkdir(parents=True, exist_ok=True)

    if format == "xlsx":
        wb = Workbook()
        ws = wb.active
        ws.title = "No Data"
        ws.cell(row=1, column=1, value="No artifacts found matching the criteria")
        file_path = exports_dir / f"matrix_{export_task_id}.xlsx"
        wb.save(str(file_path))
    else:
        file_path = exports_dir / f"matrix_{export_task_id}.csv"
        with open(file_path, "w") as f:
            f.write("No artifacts found matching the criteria\n")

    return str(file_path)


async def _update_export_status(
    export_task_id: str,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    """Update ExportTask status in database."""
    async with AsyncSessionLocal() as db:
        # Only stamp started_at when the task actually starts processing. Setting
        # it for terminal states (e.g. "failed") would clobber the real start
        # time that process_export_task already recorded, corrupting duration.
        values: dict = {"status": status, "error_message": error_message}
        if status == "processing":
            values["started_at"] = datetime.now(timezone.utc)
        stmt = update(ExportTask).where(ExportTask.task_id == export_task_id).values(**values)
        await db.execute(stmt)
        await db.commit()


async def _finalize_export(
    export_task_id: str,
    file_path: str,
    file_size: int,
) -> None:
    """Finalize export task with file information."""
    async with AsyncSessionLocal() as db:
        stmt = (
            update(ExportTask)
            .where(ExportTask.task_id == export_task_id)
            .values(
                status="completed",
                file_path=file_path,
                file_size_bytes=file_size,
                completed_at=datetime.now(timezone.utc),
                progress_pct=100.0,
            )
        )
        await db.execute(stmt)
        await db.commit()


redis_client: Any = cast(Any, _redis_client)
