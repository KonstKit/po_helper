"""
Standard pagination schema and utilities for consistent API responses.

Provides:
1. Cursor-based and offset pagination
2. Consistent response format
3. Pagination metadata
4. Link headers for HATEOAS compliance
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


# =============================================================================
# Pagination Request Parameters
# =============================================================================


class OffsetPaginationParams(BaseModel):
    """Standard offset-based pagination parameters."""

    skip: int = Field(default=0, ge=0, description="Number of records to skip")
    limit: int = Field(
        default=50, ge=1, le=1000, description="Maximum number of records to return (max 1000)"
    )

    @property
    def page(self) -> int:
        """Calculate current page number (1-indexed)."""
        return (self.skip // self.limit) + 1 if self.limit > 0 else 1


class CursorPaginationParams(BaseModel):
    """
    Cursor-based pagination parameters.

    More efficient for large datasets as it doesn't require counting total.
    """

    cursor: Optional[str] = Field(
        default=None, description="Opaque cursor for next page (base64 encoded)"
    )
    limit: int = Field(
        default=50, ge=1, le=500, description="Maximum number of records to return (max 500)"
    )
    sort_by: str = Field(default="id", description="Column to sort by")
    sort_order: str = Field(default="asc", pattern="^(asc|desc)$")

    def decode_cursor(self) -> Optional[Dict[str, Any]]:
        """Decode the cursor to get the last seen value."""
        if not self.cursor:
            return None

        try:
            decoded = base64.urlsafe_b64decode(self.cursor.encode()).decode()
            return json.loads(decoded)
        except Exception:
            return None

    @staticmethod
    def encode_cursor(last_value: Any, last_id: int) -> str:
        """Encode the cursor for the next page."""
        data = json.dumps({"v": str(last_value), "id": last_id})
        return base64.urlsafe_b64encode(data.encode()).decode()


# =============================================================================
# Pagination Response Schemas
# =============================================================================


class PaginationMeta(BaseModel):
    """Metadata for paginated responses."""

    total: int = Field(description="Total number of records")
    page: int = Field(description="Current page number (1-indexed)")
    per_page: int = Field(description="Records per page")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there is a next page")
    has_prev: bool = Field(description="Whether there is a previous page")

    @classmethod
    def from_offset(cls, total: int, skip: int, limit: int) -> "PaginationMeta":
        """Create metadata from offset pagination parameters."""
        total_pages = (total + limit - 1) // limit if limit > 0 else 1
        page = (skip // limit) + 1 if limit > 0 else 1

        return cls(
            total=total,
            page=page,
            per_page=limit,
            total_pages=max(1, total_pages),
            has_next=page < total_pages,
            has_prev=page > 1,
        )


class CursorMeta(BaseModel):
    """Metadata for cursor-based paginated responses."""

    count: int = Field(description="Number of records in current page")
    has_more: bool = Field(description="Whether there are more records")
    next_cursor: Optional[str] = Field(
        default=None, description="Cursor for the next page (null if no more pages)"
    )
    prev_cursor: Optional[str] = Field(
        default=None, description="Cursor for the previous page (null if first page)"
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Standard paginated response wrapper.

    Usage:
        @router.get("/tasks", response_model=PaginatedResponse[TaskSchema])
        async def list_tasks(...):
            return PaginatedResponse(
                data=tasks,
                meta=PaginationMeta.from_offset(total, skip, limit)
            )
    """

    data: List[T] = Field(description="List of records for current page")
    meta: PaginationMeta = Field(description="Pagination metadata")


class CursorPaginatedResponse(BaseModel, Generic[T]):
    """
    Cursor-based paginated response wrapper.

    More efficient for large datasets.
    """

    data: List[T] = Field(description="List of records for current page")
    meta: CursorMeta = Field(description="Cursor pagination metadata")


# =============================================================================
# Pagination Utilities
# =============================================================================


async def paginate_with_count(
    db: AsyncSession,
    query: Select,
    model: type,
    skip: int = 0,
    limit: int = 50,
    filters: Optional[List] = None,
) -> tuple[List[Any], int]:
    """
    Execute paginated query with total count.

    Executes count and data queries in parallel for efficiency.

    Args:
        db: AsyncSession
        query: Base select query
        model: SQLAlchemy model (for count query)
        skip: Offset
        limit: Page size
        filters: Optional filter conditions

    Returns:
        (list of records, total count)
    """
    # Build count query
    count_query = select(func.count()).select_from(model)
    if filters:
        count_query = count_query.where(and_(*filters))

    # Apply pagination to data query
    paginated_query = query.offset(skip).limit(limit)

    # Execute both queries (could be parallelized with asyncio.gather for PG)
    count_result = await db.execute(count_query)
    data_result = await db.execute(paginated_query)

    total = count_result.scalar() or 0
    records = list(data_result.scalars().all())

    return records, total


async def cursor_paginate(
    db: AsyncSession,
    query: Select,
    model: type,
    params: CursorPaginationParams,
    id_column: str = "id",
) -> tuple[List[Any], CursorMeta]:
    """
    Execute cursor-based pagination.

    More efficient than offset pagination for large datasets.

    Args:
        db: AsyncSession
        query: Base select query
        model: SQLAlchemy model
        params: Cursor pagination parameters
        id_column: Column name for unique ID

    Returns:
        (list of records, cursor metadata)
    """
    sort_col = getattr(model, params.sort_by, None)
    id_col = getattr(model, id_column)

    if sort_col is None:
        sort_col = id_col

    # Apply cursor filter if provided
    cursor_data = params.decode_cursor()
    if cursor_data:
        last_value = cursor_data.get("v")
        last_id = cursor_data.get("id")

        if params.sort_order == "desc":
            query = query.where(
                or_(sort_col < last_value, and_(sort_col == last_value, id_col < last_id))
            )
        else:
            query = query.where(
                or_(sort_col > last_value, and_(sort_col == last_value, id_col > last_id))
            )

    # Apply sort order
    if params.sort_order == "desc":
        query = query.order_by(desc(sort_col), desc(id_col))
    else:
        query = query.order_by(sort_col, id_col)

    # Fetch one extra to check for more
    query = query.limit(params.limit + 1)

    result = await db.execute(query)
    records = list(result.scalars().all())

    has_more = len(records) > params.limit
    if has_more:
        records = records[: params.limit]

    # Build next cursor
    next_cursor = None
    if has_more and records:
        last_record = records[-1]
        last_value = getattr(last_record, params.sort_by, None)
        last_id = getattr(last_record, id_column)
        next_cursor = CursorPaginationParams.encode_cursor(last_value, last_id)

    meta = CursorMeta(
        count=len(records),
        has_more=has_more,
        next_cursor=next_cursor,
        prev_cursor=params.cursor,  # Current cursor becomes prev for going back
    )

    return records, meta


# =============================================================================
# Pagination Factory Functions (for use in endpoints)
# =============================================================================


def paginated_response(data: List[Any], total: int, skip: int, limit: int) -> Dict[str, Any]:
    """
    Create a standardized paginated response dict.

    Usage in endpoints:
        return paginated_response(tasks, total_count, skip, limit)
    """
    meta = PaginationMeta.from_offset(total, skip, limit)

    return {
        "data": data,
        "meta": meta.model_dump(),
        "pagination": {  # Legacy format for backward compatibility
            "total": total,
            "skip": skip,
            "limit": limit,
            "page": meta.page,
            "total_pages": meta.total_pages,
            "has_next": meta.has_next,
            "has_prev": meta.has_prev,
        },
    }


def cursor_response(data: List[Any], meta: CursorMeta) -> Dict[str, Any]:
    """
    Create a standardized cursor-paginated response dict.
    """
    return {"data": data, "meta": meta.model_dump()}


# =============================================================================
# Link Header Builder (for HATEOAS compliance)
# =============================================================================


def build_pagination_links(base_url: str, skip: int, limit: int, total: int) -> Dict[str, str]:
    """
    Build pagination link headers.

    Returns dict suitable for adding to response headers.
    """
    meta = PaginationMeta.from_offset(total, skip, limit)
    links = {}

    # First page
    links["first"] = f"{base_url}?skip=0&limit={limit}"

    # Last page
    last_skip = (meta.total_pages - 1) * limit
    links["last"] = f"{base_url}?skip={last_skip}&limit={limit}"

    # Previous page
    if meta.has_prev:
        prev_skip = max(0, skip - limit)
        links["prev"] = f"{base_url}?skip={prev_skip}&limit={limit}"

    # Next page
    if meta.has_next:
        next_skip = skip + limit
        links["next"] = f"{base_url}?skip={next_skip}&limit={limit}"

    return links


def format_link_header(links: Dict[str, str]) -> str:
    """
    Format links dict as HTTP Link header value.

    Returns:
        String like: <url>; rel="next", <url>; rel="prev"
    """
    parts = []
    for rel, url in links.items():
        parts.append(f'<{url}>; rel="{rel}"')
    return ", ".join(parts)
