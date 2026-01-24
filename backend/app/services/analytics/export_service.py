"""Export Service - Generate RTM matrix exports in various formats.

Provides:
- CSV export
- XLSX export with formatting
- Background task processing
"""

from __future__ import annotations

import csv
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.traceability import ExportTask
from app.schemas.traceability import RTMFilters, RTMPagination
from app.services.analytics.rtm_matrix_service import get_rtm_matrix

logger = logging.getLogger(__name__)

# Export limits to prevent memory exhaustion
MAX_EXPORT_ROWS = 5000
MAX_EXPORT_COLS = 1000
MAX_EXPORT_CELLS = MAX_EXPORT_ROWS * MAX_EXPORT_COLS  # 5M max


def _get_validated_export_dir() -> Path:
    """Get and validate export directory, preventing path traversal."""
    raw_dir = getattr(settings, "EXPORTS_DIR", "/tmp/po_helper_exports")
    export_path = Path(raw_dir).resolve()

    # Validate the path is safe (not escaping to sensitive directories)
    forbidden_prefixes = ["/etc", "/var/log", "/root", "/home"]
    path_str = str(export_path)

    for prefix in forbidden_prefixes:
        if path_str.startswith(prefix) and prefix != "/tmp":
            logger.warning(
                "export.unsafe_path path=%s, falling back to /tmp/po_helper_exports",
                path_str,
            )
            export_path = Path("/tmp/po_helper_exports").resolve()
            break

    return export_path


# Validated export directory
EXPORT_DIR = _get_validated_export_dir()


async def process_export_task(
    db: AsyncSession,
    task_id: str,
) -> Dict[str, Any]:
    """
    Process an export task and generate the file.

    Args:
        db: Database session
        task_id: Export task ID

    Returns:
        Dict with status and file path
    """
    logger.info("export.process_task task_id=%s", task_id)

    # Get task from database
    stmt = select(ExportTask).where(ExportTask.task_id == task_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if not task:
        logger.error("export.task_not_found task_id=%s", task_id)
        return {"status": "error", "message": "Task not found"}

    try:
        # Update status to processing
        task.status = "processing"
        task.started_at = datetime.now(timezone.utc)
        await db.commit()

        # Get configuration
        config = task.config_json or {}
        include_details = config.get("include_details", False)

        # Load filters: start with matrix_config (if provided), then override with explicit filters
        # This implements the contract: "filters from payload override config values"
        matrix_config_id = config.get("matrix_config_id")
        explicit_filters = config.get("filters") or {}

        # Start with base filters (empty or from matrix_config)
        base_filter_dict: Dict[str, Any] = {}

        if matrix_config_id:
            # Load saved matrix config as base
            from app.models.traceability import MatrixConfig as MatrixConfigModel
            config_stmt = select(MatrixConfigModel).where(MatrixConfigModel.id == matrix_config_id)
            config_result = await db.execute(config_stmt)
            matrix_config = config_result.scalar_one_or_none()
            if matrix_config and matrix_config.filters_json:
                base_filter_dict = dict(matrix_config.filters_json)
                logger.info(
                    "export.loaded_matrix_config task_id=%s matrix_config_id=%s",
                    task_id,
                    matrix_config_id,
                )
            else:
                logger.warning(
                    "export.matrix_config_not_found task_id=%s matrix_config_id=%s",
                    task_id,
                    matrix_config_id,
                )

        # Merge explicit filters over base (explicit filters take priority)
        # Only override non-None values from explicit_filters
        for key, value in explicit_filters.items():
            if value is not None:
                base_filter_dict[key] = value

        filters = RTMFilters(**base_filter_dict) if base_filter_dict else RTMFilters()

        logger.debug(
            "export.filters_applied task_id=%s filters=%s",
            task_id,
            filters.model_dump(exclude_none=True),
        )

        # Get matrix data with hard limits to prevent memory exhaustion
        # (MAX_EXPORT_ROWS x MAX_EXPORT_COLS = 5M cells max)
        matrix_data = await get_rtm_matrix(
            db=db,
            project_id=task.project_id,
            row_types=filters.row_types,
            col_types=filters.col_types,
            row_statuses=filters.row_statuses,
            col_statuses=filters.col_statuses,
            link_types=filters.link_types,
            min_confidence=filters.min_confidence,
            search_query=filters.search_query,  # Added: text search filter
            direction=filters.direction,
            include_orphans=filters.include_orphans,
            row_skip=0,
            row_limit=min(MAX_EXPORT_ROWS, 10000),
            col_skip=0,
            col_limit=min(MAX_EXPORT_COLS, 10000),
            include_link_details=include_details,
        )

        # Generate file based on format
        if task.format == "csv":
            file_path, file_size = await _generate_csv(task_id, matrix_data)
        elif task.format == "xlsx":
            file_path, file_size = await _generate_xlsx(task_id, matrix_data)
        elif task.format == "pdf":
            file_path, file_size = await _generate_pdf(task_id, matrix_data)
        else:
            raise ValueError(f"Unsupported format: {task.format}")

        # Update task with results
        task.status = "completed"
        task.progress_pct = 100.0
        task.file_path = str(file_path)
        task.file_size_bytes = file_size
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info(
            "export.completed task_id=%s format=%s size=%d",
            task_id,
            task.format,
            file_size,
        )

        return {
            "status": "completed",
            "file_path": str(file_path),
            "file_size": file_size,
        }

    except Exception as e:
        logger.exception("export.error task_id=%s", task_id)
        task.status = "failed"
        task.error_message = str(e)
        task.completed_at = datetime.now(timezone.utc)
        await db.commit()

        return {"status": "failed", "message": str(e)}


async def _generate_csv(
    task_id: str,
    matrix_data: Dict[str, Any],
) -> tuple[Path, int]:
    """Generate CSV export file."""
    # Ensure export directory exists
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    file_path = EXPORT_DIR / f"rtm_matrix_{task_id}.csv"

    rows = matrix_data.get("rows", [])
    columns = matrix_data.get("columns", [])
    cells = matrix_data.get("cells", {})

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row: empty cell + column headers
    header = ["Row ID", "Row Type", "Row Key", "Row Title"]
    for col in columns:
        col_key = col.get("display_key") or col.get("external_id")
        header.append(f"{col_key}")
    writer.writerow(header)

    # Data rows
    for row in rows:
        row_id = str(row.get("id"))
        row_key = row.get("display_key") or row.get("external_id")
        data_row = [
            row_id,
            row.get("type", ""),
            row_key,
            row.get("title", ""),
        ]

        for col in columns:
            col_id = str(col.get("id"))
            cell = cells.get(row_id, {}).get(col_id, {})
            if cell.get("has_link"):
                link_types = cell.get("link_types", [])
                confidence = cell.get("avg_confidence")
                cell_value = ",".join(link_types)
                if confidence is not None:
                    cell_value += f" ({confidence:.0%})"
            else:
                cell_value = ""
            data_row.append(cell_value)

        writer.writerow(data_row)

    # Add coverage summary
    writer.writerow([])
    writer.writerow(["Coverage Summary"])
    coverage = matrix_data.get("coverage", {})
    writer.writerow(["Total Rows", coverage.get("total_rows", 0)])
    writer.writerow(["Rows with Links", coverage.get("rows_with_links", 0)])
    writer.writerow(["Row Coverage %", f"{coverage.get('row_coverage_pct', 0):.1f}%"])
    writer.writerow(["Total Links", coverage.get("total_links", 0)])

    # Write to file
    content = output.getvalue()
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    file_size = file_path.stat().st_size

    return file_path, file_size


async def _generate_xlsx(
    task_id: str,
    matrix_data: Dict[str, Any],
) -> tuple[Path, int]:
    """Generate XLSX export file with formatting."""
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        logger.warning("openpyxl not installed, falling back to CSV format")
        # Fallback to CSV if openpyxl not available - keep as CSV, don't fake xlsx
        csv_path, csv_size = await _generate_csv(task_id, matrix_data)
        # Return CSV path as-is; caller should handle format mismatch
        return csv_path, csv_size

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = EXPORT_DIR / f"rtm_matrix_{task_id}.xlsx"

    rows = matrix_data.get("rows", [])
    columns = matrix_data.get("columns", [])
    cells = matrix_data.get("cells", {})
    coverage = matrix_data.get("coverage", {})

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "RTM Matrix"

    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    link_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    no_link_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Header row
    headers = ["Row ID", "Type", "Key", "Title"] + [
        col.get("display_key") or col.get("external_id") for col in columns
    ]

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    for row_idx, row in enumerate(rows, 2):
        row_id = str(row.get("id"))

        ws.cell(row=row_idx, column=1, value=row_id).border = thin_border
        ws.cell(row=row_idx, column=2, value=row.get("type", "")).border = thin_border
        ws.cell(
            row=row_idx, column=3, value=row.get("display_key") or row.get("external_id")
        ).border = thin_border
        ws.cell(row=row_idx, column=4, value=row.get("title", "")).border = thin_border

        for col_offset, col in enumerate(columns):
            col_id = str(col.get("id"))
            col_idx = 5 + col_offset
            cell_data = cells.get(row_id, {}).get(col_id, {})

            cell = ws.cell(row=row_idx, column=col_idx)
            cell.border = thin_border

            if cell_data.get("has_link"):
                link_types = cell_data.get("link_types", [])
                confidence = cell_data.get("avg_confidence")
                cell_value = ",".join(link_types)
                if confidence is not None:
                    cell_value += f" ({confidence:.0%})"
                cell.value = cell_value
                cell.fill = link_fill
            else:
                cell.value = ""
                cell.fill = no_link_fill

            cell.alignment = Alignment(horizontal="center")

    # Adjust column widths
    for col_idx in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 15

    # Add coverage summary sheet
    ws_summary = wb.create_sheet("Coverage Summary")
    summary_data = [
        ("Metric", "Value"),
        ("Total Rows", coverage.get("total_rows", 0)),
        ("Total Columns", coverage.get("total_columns", 0)),
        ("Rows with Links", coverage.get("rows_with_links", 0)),
        ("Rows without Links", coverage.get("rows_without_links", 0)),
        ("Row Coverage %", f"{coverage.get('row_coverage_pct', 0):.1f}%"),
        ("Column Coverage %", f"{coverage.get('col_coverage_pct', 0):.1f}%"),
        ("Total Links", coverage.get("total_links", 0)),
        ("Traceability Density %", f"{coverage.get('traceability_density_pct', 0):.1f}%"),
    ]

    for row_idx, (metric, value) in enumerate(summary_data, 1):
        ws_summary.cell(row=row_idx, column=1, value=metric)
        ws_summary.cell(row=row_idx, column=2, value=value)
        if row_idx == 1:
            ws_summary.cell(row=row_idx, column=1).font = Font(bold=True)
            ws_summary.cell(row=row_idx, column=2).font = Font(bold=True)

    ws_summary.column_dimensions["A"].width = 25
    ws_summary.column_dimensions["B"].width = 15

    # Save workbook
    wb.save(file_path)
    file_size = file_path.stat().st_size

    return file_path, file_size


async def _generate_pdf(
    task_id: str,
    matrix_data: Dict[str, Any],
) -> tuple[Path, int]:
    """Generate PDF export file with RTM matrix table."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            SimpleDocTemplate,
            Table,
            TableStyle,
            Paragraph,
            Spacer,
            PageBreak,
        )
    except ImportError as e:
        logger.error("reportlab not installed, PDF export unavailable")
        raise ValueError(
            "PDF export requires 'reportlab' library. Please install it or use CSV/XLSX format."
        ) from e

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    file_path = EXPORT_DIR / f"rtm_matrix_{task_id}.pdf"

    rows = matrix_data.get("rows", []) or []
    columns = matrix_data.get("columns", []) or []
    cells = matrix_data.get("cells", {}) or {}
    coverage = matrix_data.get("coverage", {}) or {}

    # Guard: empty matrix - create minimal PDF with message
    if not rows and not columns:
        logger.warning("export.pdf.empty_matrix task_id=%s", task_id)
        doc = SimpleDocTemplate(
            str(file_path),
            pagesize=landscape(A4),
            rightMargin=0.5 * inch,
            leftMargin=0.5 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
        )
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("Requirements Traceability Matrix", styles["Heading1"]),
            Spacer(1, 24),
            Paragraph("No data available. The matrix is empty.", styles["Normal"]),
        ]
        doc.build(elements)
        return file_path, file_path.stat().st_size

    # Create PDF document (landscape for wide matrices)
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=landscape(A4),
        rightMargin=0.5 * inch,
        leftMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    elements = []
    styles = getSampleStyleSheet()

    # Title
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=12,
    )
    elements.append(Paragraph("Requirements Traceability Matrix", title_style))
    elements.append(Spacer(1, 12))

    # Coverage summary
    summary_text = (
        f"Row Coverage: {coverage.get('row_coverage_pct', 0):.1f}% | "
        f"Total Links: {coverage.get('total_links', 0)} | "
        f"Rows: {coverage.get('total_rows', 0)} | "
        f"Columns: {coverage.get('total_columns', 0)}"
    )
    elements.append(Paragraph(summary_text, styles["Normal"]))
    elements.append(Spacer(1, 12))

    # Column chunking to avoid truncation while keeping pages readable
    page_width, _ = landscape(A4)
    available_width = page_width - (0.5 * inch) * 2
    min_meta_widths = [0.6 * inch, 0.7 * inch, 1.0 * inch, 2.4 * inch]
    min_data_width = 0.45 * inch
    max_data_cols = max(1, int((available_width - sum(min_meta_widths)) // min_data_width))
    if max_data_cols < 1:
        max_data_cols = 1

    total_columns = len(columns)
    if total_columns == 0:
        header = ["ID", "Type", "Key", "Title"]
        table_data = [header]
        for row in rows:
            row_id = str(row.get("id"))
            data_row = [
                row_id,
                row.get("type", "") or "",
                row.get("display_key") or row.get("external_id") or "",
                row.get("title", "") or "",
            ]
            table_data.append(data_row)

        col_widths = min_meta_widths[:]
        extra_width = max(available_width - sum(col_widths), 0)
        col_widths[3] += extra_width

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.27, 0.45, 0.77)),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 7),
                    ("ALIGN", (0, 1), (-1, -1), "LEFT"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
                ]
            )
        )
        elements.append(table)
    else:
        for chunk_idx in range(0, total_columns, max_data_cols):
            display_columns = columns[chunk_idx:chunk_idx + max_data_cols]

            chunk_label = f"Columns {chunk_idx + 1}-{chunk_idx + len(display_columns)} of {total_columns}"
            elements.append(Paragraph(chunk_label, styles["Italic"]))
            elements.append(Spacer(1, 6))

            header = ["ID", "Type", "Key", "Title"]
            for col in display_columns:
                col_key = col.get("display_key") or col.get("external_id") or str(col.get("id"))
                header.append(col_key)

            table_data = [header]

            for row in rows:
                row_id = str(row.get("id"))
                data_row = [
                    row_id,
                    row.get("type", "") or "",
                    row.get("display_key") or row.get("external_id") or "",
                    row.get("title", "") or "",
                ]

                for col in display_columns:
                    col_id = str(col.get("id"))
                    cell = cells.get(row_id, {}).get(col_id, {})
                    if cell.get("has_link"):
                        link_count = cell.get("link_count", 1)
                        confidence = cell.get("avg_confidence")
                        if confidence is not None:
                            cell_value = f"{link_count}({confidence:.0%})"
                        else:
                            cell_value = str(link_count)
                    else:
                        cell_value = "-"
                    data_row.append(cell_value)

                table_data.append(data_row)

            col_widths = min_meta_widths[:]
            data_width = max(
                min_data_width,
                (available_width - sum(min_meta_widths)) / max(len(display_columns), 1),
            )
            col_widths += [data_width] * len(display_columns)
            extra_width = max(available_width - sum(col_widths), 0)
            col_widths[3] += extra_width

            table = Table(table_data, colWidths=col_widths, repeatRows=1)

            table_style = TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.27, 0.45, 0.77)),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 7),
                ("ALIGN", (0, 1), (3, -1), "LEFT"),
                ("ALIGN", (4, 1), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.Color(0.95, 0.95, 0.95)]),
            ])

            for row_idx, row in enumerate(rows, 1):
                row_id = str(row.get("id"))
                for col_offset, col in enumerate(display_columns):
                    col_id = str(col.get("id"))
                    cell = cells.get(row_id, {}).get(col_id, {})
                    if cell.get("has_link"):
                        table_style.add(
                            "BACKGROUND",
                            (4 + col_offset, row_idx),
                            (4 + col_offset, row_idx),
                            colors.Color(0.78, 0.94, 0.81),
                        )

            table.setStyle(table_style)
            elements.append(table)

            if chunk_idx + max_data_cols < total_columns:
                elements.append(PageBreak())

    # Build PDF
    try:
        doc.build(elements)
    except Exception as e:
        logger.exception("export.pdf.build_failed task_id=%s", task_id)
        # Clean up partial file if it exists
        if file_path.exists():
            file_path.unlink()
        raise ValueError(f"PDF generation failed: {e}") from e

    file_size = file_path.stat().st_size

    return file_path, file_size


async def get_export_file_path(
    db: AsyncSession,
    task_id: str,
) -> Optional[Path]:
    """Get the file path for a completed export task."""
    stmt = select(ExportTask).where(
        ExportTask.task_id == task_id,
        ExportTask.status == "completed",
    )
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()

    if task and task.file_path:
        path = Path(task.file_path)
        if path.exists():
            return path

    return None


async def cleanup_old_exports(
    db: AsyncSession,
    max_age_hours: int = 24,
) -> int:
    """Clean up old export files and tasks."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    # Find old tasks
    stmt = select(ExportTask).where(ExportTask.created_at < cutoff)
    result = await db.execute(stmt)
    old_tasks = result.scalars().all()

    deleted_count = 0

    for task in old_tasks:
        # Delete file if exists
        if task.file_path:
            try:
                path = Path(task.file_path)
                if path.exists():
                    path.unlink()
            except Exception as e:
                logger.warning("Failed to delete export file: %s", e)

        # Delete task record
        await db.delete(task)
        deleted_count += 1

    await db.commit()

    logger.info("export.cleanup deleted=%d", deleted_count)
    return deleted_count
