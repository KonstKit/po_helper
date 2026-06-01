"""RTM Matrix Service - Requirements Traceability Matrix query service.

Provides:
- Sparse RTM matrix with server-side pagination
- Row/column selectors by artifact type, status, search
- Link type filtering
- Bidirectional link support
- Coverage statistics
"""

from __future__ import annotations

import logging
from collections import defaultdict
from time import perf_counter
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import metrics
from app.models.traceability import Artifact, ArtifactLink
from app.utils.confidence import confidence_filter, normalize_confidence

logger = logging.getLogger(__name__)


def _record_matrix_metrics(
    *,
    duration_seconds: float,
    rows_returned: int,
    columns_returned: int,
    links_returned: int,
    outcome: str,
) -> None:
    try:
        labels = {"outcome": outcome}
        metrics.observe("rtm_matrix_query_duration_seconds", duration_seconds, labels=labels)
        metrics.observe("rtm_matrix_rows_returned", float(rows_returned), labels=labels)
        metrics.observe("rtm_matrix_columns_returned", float(columns_returned), labels=labels)
        metrics.observe("rtm_matrix_links_returned", float(links_returned), labels=labels)
    except Exception:
        pass


async def get_rtm_matrix(
    db: AsyncSession,
    project_id: Optional[int] = None,
    row_types: Optional[List[str]] = None,
    col_types: Optional[List[str]] = None,
    row_statuses: Optional[List[str]] = None,
    col_statuses: Optional[List[str]] = None,
    link_types: Optional[List[str]] = None,
    min_confidence: float = 0.0,
    search_query: Optional[str] = None,
    direction: str = "both",
    include_orphans: bool = False,
    row_skip: int = 0,
    row_limit: int = 50,
    col_skip: int = 0,
    col_limit: int = 50,
    include_link_details: bool = False,
) -> Dict[str, Any]:
    """
    Build RTM matrix with server-side pagination and filtering.

    Args:
        db: Database session
        project_id: Filter by project (optional)
        row_types: Artifact types for rows (e.g., ['requirement'])
        col_types: Artifact types for columns (e.g., ['test_case', 'jira_issue'])
        row_statuses: Filter rows by status
        col_statuses: Filter columns by status
        link_types: Link types to include
        min_confidence: Minimum confidence threshold
        search_query: Text search in artifact titles
        direction: Link direction - 'outgoing', 'incoming', or 'both'
        include_orphans: Include artifacts without links
        row_skip: Pagination offset for rows
        row_limit: Max rows to return
        col_skip: Pagination offset for columns
        col_limit: Max columns to return
        include_link_details: Include full link info in cells

    Returns:
        RTM matrix with rows, columns, cells, and coverage stats
    """
    start = perf_counter()
    rows_returned = 0
    columns_returned = 0
    links_returned = 0
    outcome = "error"
    logger.info(
        "rtm_matrix.start project_id=%s row_types=%s col_types=%s",
        project_id,
        row_types,
        col_types,
    )

    try:
        # --- Step 1: Query row artifacts ---
        row_artifacts, total_rows = await _query_artifacts(
            db,
            project_id=project_id,
            artifact_types=row_types,
            statuses=row_statuses,
            search_query=search_query,
            skip=row_skip,
            limit=row_limit,
            include_orphans=include_orphans,
        )

        # --- Step 2: Query column artifacts ---
        col_artifacts, total_cols = await _query_artifacts(
            db,
            project_id=project_id,
            artifact_types=col_types,
            statuses=col_statuses,
            search_query=search_query,
            skip=col_skip,
            limit=col_limit,
            include_orphans=include_orphans,
        )

        if not row_artifacts or not col_artifacts:
            rows_returned = 0
            columns_returned = 0
            links_returned = 0
            outcome = "success"
            return _empty_matrix_response(
                total_rows=total_rows,
                total_cols=total_cols,
                row_types=row_types,
                col_types=col_types,
            )

        row_ids = [a.id for a in row_artifacts]
        col_ids = [a.id for a in col_artifacts]

        # --- Step 3: Query links between row and column artifacts ---
        links = await _query_links(
            db,
            row_ids=row_ids,
            col_ids=col_ids,
            link_types=link_types,
            min_confidence=min_confidence,
            direction=direction,
            project_id=project_id,
        )

        # --- Step 4: Build matrix cells ---
        cells, link_stats = _build_cells(
            links=links,
            row_ids=set(row_ids),
            col_ids=set(col_ids),
            direction=direction,
            include_details=include_link_details,
        )

        # --- Step 5: Calculate coverage stats ---
        coverage = _calculate_coverage(
            row_artifacts=row_artifacts,
            col_artifacts=col_artifacts,
            cells=cells,
            link_stats=link_stats,
        )

        # --- Step 6: Format response ---
        rows = [_artifact_to_summary(a) for a in row_artifacts]
        columns = [_artifact_to_summary(a) for a in col_artifacts]

        filters_applied = {
            "row_types": row_types,
            "col_types": col_types,
            "row_statuses": row_statuses,
            "col_statuses": col_statuses,
            "link_types": link_types,
            "min_confidence": min_confidence,
            "direction": direction,
            "search_query": search_query,
            "include_orphans": include_orphans,
        }

        response = {
            "rows": rows,
            "columns": columns,
            "cells": cells,
            "total_rows": total_rows,
            "total_columns": total_cols,
            "coverage": coverage,
            "filters_applied": filters_applied,
        }

        rows_returned = len(rows)
        columns_returned = len(columns)
        links_returned = int(link_stats.get("total_links", 0))
        outcome = "success"
        duration = perf_counter() - start
        logger.info(
            "rtm_matrix.success project_id=%s rows=%s cols=%s links=%s duration=%.3f",
            project_id,
            rows_returned,
            columns_returned,
            links_returned,
            duration,
        )

        return response

    except Exception:
        outcome = "error"
        logger.exception(
            "rtm_matrix.error project_id=%s duration=%.3f",
            project_id,
            perf_counter() - start,
        )
        raise
    finally:
        _record_matrix_metrics(
            duration_seconds=perf_counter() - start,
            rows_returned=rows_returned,
            columns_returned=columns_returned,
            links_returned=links_returned,
            outcome=outcome,
        )


async def _query_artifacts(
    db: AsyncSession,
    project_id: Optional[int],
    artifact_types: Optional[List[str]],
    statuses: Optional[List[str]],
    search_query: Optional[str],
    skip: int,
    limit: int,
    include_orphans: bool = True,
) -> Tuple[List[Artifact], int]:
    """Query artifacts with filters and pagination.

    Args:
        include_orphans: If False, only include artifacts that have at least one link.
    """
    # Base query
    stmt = select(Artifact)
    count_stmt = select(func.count(Artifact.id))

    # Apply filters
    conditions = []

    if project_id is not None:
        conditions.append(Artifact.project_id == project_id)

    if artifact_types:
        conditions.append(Artifact.type.in_(artifact_types))

    if statuses:
        conditions.append(Artifact.status.in_(statuses))

    if search_query:
        # Sanitize and limit input to prevent DoS and injection
        sanitized_query = (
            search_query.replace("\x00", "")[
                # Remove null bytes
                :500
            ]  # Limit length to prevent DoS
        )
        # Escape SQL LIKE wildcards to prevent injection
        escaped_query = (
            sanitized_query.replace("\\", "\\\\")  # Escape backslash first
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        search_pattern = f"%{escaped_query}%"
        conditions.append(
            or_(
                Artifact.title.ilike(search_pattern, escape="\\"),
                Artifact.display_key.ilike(search_pattern, escape="\\"),
                Artifact.external_id.ilike(search_pattern, escape="\\"),
            )
        )

    if conditions:
        stmt = stmt.where(and_(*conditions))
        count_stmt = count_stmt.where(and_(*conditions))

    # Filter out orphaned artifacts (those without any links)
    if not include_orphans:
        has_outgoing_link = exists().where(ArtifactLink.from_artifact_id == Artifact.id)
        has_incoming_link = exists().where(ArtifactLink.to_artifact_id == Artifact.id)
        orphan_filter = or_(has_outgoing_link, has_incoming_link)
        stmt = stmt.where(orphan_filter)
        count_stmt = count_stmt.where(orphan_filter)

    # Get total count
    total = (await db.execute(count_stmt)).scalar() or 0

    # Apply pagination and ordering (NULLS LAST for deterministic results)
    stmt = stmt.order_by(
        Artifact.type,
        Artifact.display_key.nulls_last(),
        Artifact.id,
    )
    stmt = stmt.offset(skip).limit(limit)

    result = await db.execute(stmt)
    artifacts = list(result.scalars().all())

    return artifacts, total


async def _query_links(
    db: AsyncSession,
    row_ids: List[int],
    col_ids: List[int],
    link_types: Optional[List[str]],
    min_confidence: float,
    direction: str,
    project_id: Optional[int],
) -> List[ArtifactLink]:
    """Query links between row and column artifacts."""
    conditions = []

    # Build direction-specific conditions
    if direction == "outgoing":
        # Links from rows to columns
        conditions.append(
            and_(
                ArtifactLink.from_artifact_id.in_(row_ids),
                ArtifactLink.to_artifact_id.in_(col_ids),
            )
        )
    elif direction == "incoming":
        # Links from columns to rows
        conditions.append(
            and_(
                ArtifactLink.from_artifact_id.in_(col_ids),
                ArtifactLink.to_artifact_id.in_(row_ids),
            )
        )
    else:  # direction == "both"
        # Links in either direction
        conditions.append(
            or_(
                and_(
                    ArtifactLink.from_artifact_id.in_(row_ids),
                    ArtifactLink.to_artifact_id.in_(col_ids),
                ),
                and_(
                    ArtifactLink.from_artifact_id.in_(col_ids),
                    ArtifactLink.to_artifact_id.in_(row_ids),
                ),
            )
        )

    stmt = select(ArtifactLink).where(or_(*conditions))

    # Filter by link types
    if link_types:
        stmt = stmt.where(ArtifactLink.link_type.in_(link_types))

    # Filter by confidence (handles legacy 0..100 data via normalization)
    if min_confidence > 0:
        stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))

    # Filter by project
    if project_id is not None:
        stmt = stmt.where(ArtifactLink.project_id == project_id)

    result = await db.execute(stmt)
    return list(result.scalars().all())


def _build_cells(
    links: List[ArtifactLink],
    row_ids: Set[int],
    col_ids: Set[int],
    direction: str,
    include_details: bool,
) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[str, Any]]:
    """Build matrix cells from links."""
    # cells[row_id][col_id] = cell_data
    cells: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    link_stats: Dict[str, Any] = {
        "total_links": 0,
        "by_type": defaultdict(int),
        "confidence_sum": 0.0,
        "confidence_count": 0,
    }

    for link in links:
        # Determine row/col mapping based on direction
        if link.from_artifact_id in row_ids and link.to_artifact_id in col_ids:
            row_id = link.from_artifact_id
            col_id = link.to_artifact_id
            link_direction = "outgoing"
        elif link.from_artifact_id in col_ids and link.to_artifact_id in row_ids:
            row_id = link.to_artifact_id
            col_id = link.from_artifact_id
            link_direction = "incoming"
        else:
            continue  # Link not relevant

        row_key = str(row_id)
        col_key = str(col_id)

        if col_key not in cells[row_key]:
            cells[row_key][col_key] = {
                "has_link": True,
                "link_count": 0,
                "link_types": [],
                "confidences": [],
                "links": [] if include_details else None,
            }

        cell = cells[row_key][col_key]
        cell["link_count"] += 1
        if link.link_type and link.link_type not in cell["link_types"]:
            cell["link_types"].append(link.link_type)

        # Normalize confidence for aggregation (handles legacy 0..100 data)
        normalized_conf = normalize_confidence(link.confidence)
        if normalized_conf is not None:
            cell["confidences"].append(normalized_conf)

        if include_details:
            cell["links"].append(
                {
                    "id": link.id,
                    "link_type": link.link_type,
                    "confidence": normalized_conf,
                    "direction": link_direction,
                    "from_id": link.from_artifact_id,
                    "to_id": link.to_artifact_id,
                }
            )

        # Update stats
        link_stats["total_links"] += 1
        link_stats["by_type"][link.link_type] += 1
        if normalized_conf is not None:
            link_stats["confidence_sum"] += normalized_conf
            link_stats["confidence_count"] += 1

    # Finalize cells - calculate avg confidence, remove intermediate data
    for row_key, row_cells in cells.items():
        for col_key, cell in row_cells.items():
            confidences = cell.pop("confidences", [])
            if confidences:
                cell["avg_confidence"] = round(sum(confidences) / len(confidences), 3)
            else:
                cell["avg_confidence"] = None

    # Convert defaultdict to regular dict for JSON serialization
    cells = {k: dict(v) for k, v in cells.items()}
    link_stats["by_type"] = dict(link_stats["by_type"])

    return cells, link_stats


def _calculate_coverage(
    row_artifacts: List[Artifact],
    col_artifacts: List[Artifact],
    cells: Dict[str, Dict[str, Dict[str, Any]]],
    link_stats: Dict[str, Any],
) -> Dict[str, Any]:
    """Calculate coverage statistics."""
    total_rows = len(row_artifacts)
    total_cols = len(col_artifacts)

    # Rows with at least one link
    rows_with_links = len(cells)
    rows_without_links = total_rows - rows_with_links

    # Columns with at least one link
    cols_with_links_set: Set[str] = set()
    for row_cells in cells.values():
        cols_with_links_set.update(row_cells.keys())
    cols_with_links = len(cols_with_links_set)
    cols_without_links = total_cols - cols_with_links

    # Coverage percentages
    row_coverage_pct = (rows_with_links / total_rows * 100) if total_rows > 0 else 0.0
    col_coverage_pct = (cols_with_links / total_cols * 100) if total_cols > 0 else 0.0

    # Overall traceability (percentage of possible cells that have links)
    total_possible_cells = total_rows * total_cols
    total_cells_with_links = sum(len(row_cells) for row_cells in cells.values())
    traceability_density = (
        (total_cells_with_links / total_possible_cells * 100) if total_possible_cells > 0 else 0.0
    )

    # Average confidence
    avg_confidence = (
        round(link_stats["confidence_sum"] / link_stats["confidence_count"], 3)
        if link_stats["confidence_count"] > 0
        else None
    )

    return {
        "total_rows": total_rows,
        "total_columns": total_cols,
        "rows_with_links": rows_with_links,
        "rows_without_links": rows_without_links,
        "cols_with_links": cols_with_links,
        "cols_without_links": cols_without_links,
        "row_coverage_pct": round(row_coverage_pct, 2),
        "col_coverage_pct": round(col_coverage_pct, 2),
        "traceability_density_pct": round(traceability_density, 2),
        "total_links": link_stats["total_links"],
        "links_by_type": link_stats["by_type"],
        "avg_confidence": avg_confidence,
    }


def _artifact_to_summary(artifact: Artifact) -> Dict[str, Any]:
    """Convert artifact to summary dict."""
    return {
        "id": artifact.id,
        "type": artifact.type,
        "source": artifact.source,
        "external_id": artifact.external_id,
        "display_key": artifact.display_key,
        "title": artifact.title,
        "status": artifact.status,
        "url": artifact.url,
    }


def _empty_matrix_response(
    total_rows: int,
    total_cols: int,
    row_types: Optional[List[str]],
    col_types: Optional[List[str]],
) -> Dict[str, Any]:
    """Return empty matrix response."""
    return {
        "rows": [],
        "columns": [],
        "cells": {},
        "total_rows": total_rows,
        "total_columns": total_cols,
        "coverage": {
            "total_rows": total_rows,
            "total_columns": total_cols,
            "rows_with_links": 0,
            "rows_without_links": total_rows,
            "cols_with_links": 0,
            "cols_without_links": total_cols,
            "row_coverage_pct": 0.0,
            "col_coverage_pct": 0.0,
            "traceability_density_pct": 0.0,
            "total_links": 0,
            "links_by_type": {},
            "avg_confidence": None,
        },
        "filters_applied": {
            "row_types": row_types,
            "col_types": col_types,
        },
    }
