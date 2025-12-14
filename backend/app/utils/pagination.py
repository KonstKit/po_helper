"""Pagination utilities for consistent list endpoints."""

from typing import Optional, List, TypeVar, Type
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


async def count_with_filters(
    db: AsyncSession,
    model: Type[T],
    filters: Optional[List] = None
) -> int:
    """
    Count total records for a model with optional filters.

    Eliminates the repetitive pattern of:
        count_query = select(func.count()).select_from(Model)
        if filters:
            count_query = count_query.where(and_(*filters))
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

    Usage:
        filters = [Model.enabled == True, Model.category == 'test']
        total = await count_with_filters(db, Model, filters)

    Args:
        db: Database session
        model: SQLAlchemy model class
        filters: Optional list of filter conditions

    Returns:
        Total count of records matching filters
    """
    count_query = select(func.count()).select_from(model)

    if filters:
        count_query = count_query.where(and_(*filters))

    result = await db.execute(count_query)
    return result.scalar() or 0


async def paginate_query(
    db: AsyncSession,
    query: Select[tuple[T]],
    skip: int = 0,
    limit: int = 100
) -> List[T]:
    """
    Apply pagination to a query and execute it.

    Eliminates the repetitive pattern of:
        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        items = result.scalars().all()

    Usage:
        query = select(Model).where(Model.active == True)
        items = await paginate_query(db, query, skip=0, limit=50)

    Args:
        db: Database session
        query: SQLAlchemy select query
        skip: Number of records to skip (default: 0)
        limit: Maximum number of records to return (default: 100)

    Returns:
        List of model instances
    """
    paginated_query = query.offset(skip).limit(limit)
    result = await db.execute(paginated_query)
    return list(result.scalars().all())
