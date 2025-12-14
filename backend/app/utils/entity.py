"""Entity retrieval utilities for consistent not found handling."""

from typing import TypeVar, Type, Optional
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

T = TypeVar("T")


async def get_or_404(
    db: AsyncSession,
    query: Select[tuple[T]],
    entity_name: str = "Entity"
) -> T:
    """
    Execute a query and return the entity or raise 404 if not found.

    Eliminates the repetitive pattern of:
        result = await db.execute(select(Model).where(Model.id == id))
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        return entity

    Usage:
        # Instead of:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Use:
        user = await get_or_404(db, select(User).where(User.id == user_id), "User")

    Args:
        db: Database session
        query: SQLAlchemy select query
        entity_name: Name of entity for error message (e.g., "User", "Project")

    Returns:
        The entity if found

    Raises:
        HTTPException: 404 if entity not found
    """
    result = await db.execute(query)
    entity = result.scalar_one_or_none()

    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_name} not found")

    return entity


async def get_by_id_or_404(
    db: AsyncSession,
    model: Type[T],
    entity_id: int,
    entity_name: Optional[str] = None
) -> T:
    """
    Get entity by ID using db.get() or raise 404 if not found.

    Eliminates the repetitive pattern of:
        entity = await db.get(Model, entity_id)
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        return entity

    Usage:
        # Instead of:
        project = await db.get(Project, project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        # Use:
        project = await get_by_id_or_404(db, Project, project_id)

    Args:
        db: Database session
        model: SQLAlchemy model class
        entity_id: Primary key value
        entity_name: Optional custom name for error message (defaults to model.__name__)

    Returns:
        The entity if found

    Raises:
        HTTPException: 404 if entity not found
    """
    entity = await db.get(model, entity_id)

    if not entity:
        name = entity_name or model.__name__
        raise HTTPException(status_code=404, detail=f"{name} not found")

    return entity
