"""
Batch operations utilities for eliminating N+1 queries.

Provides patterns for:
1. Bulk delete with single query
2. Batch fetch with IN clause
3. Optimized graph traversal
4. Bulk update operations
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    TypedDict,
    Protocol,
    runtime_checkable,
)

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


@runtime_checkable
class HasId(Protocol):
    id: Any
    __tablename__: str


class DeleteResult(TypedDict):
    deleted: int
    dependents_deleted: Dict[str, int]


logger = logging.getLogger(__name__)

T = TypeVar("T", bound=HasId)


# =============================================================================
# Bulk Delete Operations (Fixing N+1 in delete endpoints)
# =============================================================================


async def bulk_delete_by_ids(
    db: AsyncSession, model: Type[T], ids: List[int], chunk_size: int = 500
) -> int:
    """
    Delete multiple records by ID in optimized chunks.

    Instead of N individual DELETE queries, uses:
    DELETE FROM table WHERE id IN (...)

    Args:
        db: AsyncSession
        model: SQLAlchemy model class
        ids: List of IDs to delete
        chunk_size: Max IDs per query to avoid parameter limits

    Returns:
        Total number of deleted records
    """
    if not ids:
        return 0

    total_deleted = 0

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        stmt = delete(model).where(model.id.in_(chunk))
        result = await db.execute(stmt)
        total_deleted += int(getattr(result, "rowcount", 0) or 0)

    await db.commit()
    return total_deleted


async def bulk_delete_with_cascade_check(
    db: AsyncSession,
    model: Type[T],
    ids: List[int],
    dependent_models: Optional[List[Tuple[Type[HasId], str]]] = None,
    chunk_size: int = 500,
) -> DeleteResult:
    """
    Delete records with optional cascade dependency check.

    Args:
        db: AsyncSession
        model: Main model to delete
        ids: List of IDs to delete
        dependent_models: List of (Model, foreign_key_column_name) tuples
        chunk_size: Max IDs per query

    Returns:
        Dict with counts: {"deleted": N, "dependents_deleted": {...}}
    """
    if not ids:
        return {"deleted": 0, "dependents_deleted": {}}

    result: DeleteResult = {"deleted": 0, "dependents_deleted": {}}

    # Delete dependents first (if specified)
    if dependent_models:
        for dep_model, fk_column in dependent_models:
            fk_attr = getattr(dep_model, fk_column)
            for i in range(0, len(ids), chunk_size):
                chunk = ids[i : i + chunk_size]
                stmt = delete(dep_model).where(fk_attr.in_(chunk))
                dep_result = await db.execute(stmt)
                dep_name = dep_model.__tablename__
                result["dependents_deleted"][dep_name] = result["dependents_deleted"].get(
                    dep_name, 0
                ) + int(getattr(dep_result, "rowcount", 0) or 0)

    # Delete main records
    result["deleted"] = await bulk_delete_by_ids(db, model, ids, chunk_size)

    return result


# =============================================================================
# Batch Fetch Operations (Fixing N+1 in list/detail endpoints)
# =============================================================================


async def batch_fetch_by_ids(
    db: AsyncSession, model: Type[T], ids: List[int], eager_load: Optional[List[str]] = None
) -> Dict[int, T]:
    """
    Fetch multiple records by ID with optional eager loading.

    Returns a dict mapping ID -> model instance for O(1) lookup.

    Args:
        db: AsyncSession
        model: SQLAlchemy model class
        ids: List of IDs to fetch
        eager_load: List of relationship names to eagerly load

    Returns:
        Dict[id, model_instance]
    """
    if not ids:
        return {}

    # Remove duplicates while preserving order
    unique_ids = list(dict.fromkeys(ids))

    stmt = select(model).where(model.id.in_(unique_ids))

    # Add eager loading for relationships
    if eager_load:
        for rel_name in eager_load:
            if hasattr(model, rel_name):
                stmt = stmt.options(selectinload(getattr(model, rel_name)))

    result = await db.execute(stmt)
    records = result.scalars().all()

    return {record.id: record for record in records}


async def batch_fetch_related(
    db: AsyncSession,
    main_model: Type[T],
    main_ids: List[int],
    related_model: Type,
    foreign_key: str,
) -> Dict[int, List[Any]]:
    """
    Batch fetch related records grouped by main record ID.

    Instead of N queries for each main record's relations,
    uses single query with GROUP BY simulation.

    Args:
        db: AsyncSession
        main_model: The main model
        main_ids: IDs of main model records
        related_model: The related model
        foreign_key: Name of FK column on related model

    Returns:
        Dict[main_id, List[related_records]]
    """
    if not main_ids:
        return {}

    fk_attr = getattr(related_model, foreign_key)
    stmt = select(related_model).where(fk_attr.in_(main_ids))
    result = await db.execute(stmt)
    related_records = result.scalars().all()

    # Group by foreign key
    grouped: Dict[int, List[Any]] = defaultdict(list)
    for record in related_records:
        fk_value = getattr(record, foreign_key)
        if fk_value is not None:
            grouped[fk_value].append(record)

    return dict(grouped)


# =============================================================================
# Optimized Graph Traversal (Fixing N+1 in cycle detection / flow graphs)
# =============================================================================


async def detect_cycles_batched(
    db: AsyncSession,
    link_model: Type,
    from_column: str,
    to_column: str,
    start_id: int,
    target_id: int,
    project_id: Optional[int] = None,
    max_depth: int = 10,
) -> bool:
    """
    Detect if adding link (start_id -> target_id) would create a cycle.

    Uses batch BFS instead of N+1 queries.

    Args:
        db: AsyncSession
        link_model: The link/edge model
        from_column: Column name for source node
        to_column: Column name for target node
        start_id: Source of new link
        target_id: Target of new link
        project_id: Optional project scope
        max_depth: Maximum traversal depth

    Returns:
        True if cycle would be created
    """
    from_attr = getattr(link_model, from_column)
    to_attr = getattr(link_model, to_column)

    # BFS from target_id to see if we can reach start_id
    visited: Set[int] = set()
    current_level: Set[int] = {target_id}
    depth = 0

    while current_level and depth < max_depth:
        if start_id in current_level:
            return True

        visited.update(current_level)

        # Batch fetch all outgoing edges from current level
        stmt = select(to_attr).where(from_attr.in_(list(current_level)))
        if project_id is not None and hasattr(link_model, "project_id"):
            stmt = stmt.where(link_model.project_id == project_id)

        result = await db.execute(stmt)
        next_ids = {row[0] for row in result.all() if row[0] is not None}

        current_level = next_ids - visited
        depth += 1

    return False


async def traverse_graph_batched(
    db: AsyncSession,
    node_model: Type,
    link_model: Type,
    start_id: int,
    from_column: str,
    to_column: str,
    max_depth: int = 5,
    project_id: Optional[int] = None,
) -> Tuple[Dict[int, Any], List[Dict[str, Any]]]:
    """
    Traverse graph from start node using batched BFS.

    Returns all reachable nodes and edges up to max_depth.

    Args:
        db: AsyncSession
        node_model: Model for nodes (e.g., Artifact)
        link_model: Model for edges (e.g., ArtifactLink)
        start_id: Starting node ID
        from_column: FK column for source
        to_column: FK column for target
        max_depth: Maximum traversal depth
        project_id: Optional project scope

    Returns:
        (nodes_dict, edges_list)
    """
    from_attr = getattr(link_model, from_column)
    nodes: Dict[int, Any] = {}
    edges: List[Dict[str, Any]] = []
    visited: Set[int] = {start_id}
    current_level: Set[int] = {start_id}
    depth = 0

    while current_level and depth < max_depth:
        # Batch fetch all outgoing links from current level
        stmt = select(link_model).where(from_attr.in_(list(current_level)))
        if project_id is not None and hasattr(link_model, "project_id"):
            stmt = stmt.where(link_model.project_id == project_id)

        result = await db.execute(stmt)
        links = result.scalars().all()

        # Collect target IDs for next level
        next_ids: Set[int] = set()

        for link in links:
            target_id = getattr(link, to_column)
            if target_id is not None:
                edges.append(
                    {
                        "from": getattr(link, from_column),
                        "to": target_id,
                        "type": getattr(link, "link_type", None),
                        "confidence": getattr(link, "confidence", None),
                    }
                )
                if target_id not in visited:
                    next_ids.add(target_id)
                    visited.add(target_id)

        # Batch fetch node data for new nodes
        if next_ids:
            node_data = await batch_fetch_by_ids(db, node_model, list(next_ids))
            nodes.update(node_data)

        current_level = next_ids
        depth += 1

    # Fetch start node
    start_node = await batch_fetch_by_ids(db, node_model, [start_id])
    nodes.update(start_node)

    return nodes, edges


# =============================================================================
# Bulk Update Operations
# =============================================================================


async def bulk_update_by_ids(
    db: AsyncSession, model: Type[T], ids: List[int], updates: Dict[str, Any], chunk_size: int = 500
) -> int:
    """
    Update multiple records by ID.

    Args:
        db: AsyncSession
        model: SQLAlchemy model class
        ids: List of IDs to update
        updates: Dict of {column_name: new_value}
        chunk_size: Max IDs per query

    Returns:
        Total number of updated records
    """
    if not ids or not updates:
        return 0

    total_updated = 0

    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        stmt = update(model).where(model.id.in_(chunk)).values(**updates)
        result = await db.execute(stmt)
        total_updated += int(getattr(result, "rowcount", 0) or 0)

    await db.commit()
    return total_updated


async def bulk_update_conditional(
    db: AsyncSession, model: Type[T], conditions: Dict[str, Any], updates: Dict[str, Any]
) -> int:
    """
    Update records matching conditions.

    Args:
        db: AsyncSession
        model: SQLAlchemy model class
        conditions: Dict of {column_name: value} for WHERE clause
        updates: Dict of {column_name: new_value}

    Returns:
        Number of updated records
    """
    if not conditions or not updates:
        return 0

    # Build WHERE clause
    where_clauses = []
    for col_name, value in conditions.items():
        col = getattr(model, col_name, None)
        if col is not None:
            if isinstance(value, (list, tuple)):
                where_clauses.append(col.in_(value))
            else:
                where_clauses.append(col == value)

    if not where_clauses:
        return 0

    stmt = update(model).where(and_(*where_clauses)).values(**updates)
    result = await db.execute(stmt)
    await db.commit()

    return int(getattr(result, "rowcount", 0) or 0)


# =============================================================================
# Aggregation Helpers (Avoiding Python-side computation)
# =============================================================================


async def aggregate_by_group(
    db: AsyncSession,
    model: Type,
    group_column: str,
    aggregations: Dict[str, Tuple[str, str]],
    filters: Optional[List] = None,
) -> List[Dict[str, Any]]:
    """
    Perform grouped aggregations in database instead of Python.

    Args:
        db: AsyncSession
        model: SQLAlchemy model
        group_column: Column to group by
        aggregations: Dict of {result_name: (column_name, agg_func)}
            agg_func can be: "count", "sum", "avg", "min", "max"
        filters: Optional list of SQLAlchemy filter expressions

    Returns:
        List of dicts with group value and aggregated results

    Example:
        results = await aggregate_by_group(
            db, Task, "status",
            {"task_count": ("id", "count"), "total_hours": ("estimate_hours", "sum")},
            filters=[Task.project_id == 123]
        )
    """
    group_col = getattr(model, group_column)

    # Build aggregation columns
    agg_cols = [group_col.label(group_column)]
    for result_name, (col_name, agg_func) in aggregations.items():
        col = getattr(model, col_name)
        if agg_func == "count":
            agg_cols.append(func.count(col).label(result_name))
        elif agg_func == "sum":
            agg_cols.append(func.sum(col).label(result_name))
        elif agg_func == "avg":
            agg_cols.append(func.avg(col).label(result_name))
        elif agg_func == "min":
            agg_cols.append(func.min(col).label(result_name))
        elif agg_func == "max":
            agg_cols.append(func.max(col).label(result_name))

    stmt = select(*agg_cols).group_by(group_col)

    if filters:
        stmt = stmt.where(and_(*filters))

    result = await db.execute(stmt)
    rows = result.mappings().all()

    return [dict(row) for row in rows]
