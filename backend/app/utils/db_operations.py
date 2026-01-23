"""Database operation utilities for transaction management."""

import logging
from contextlib import asynccontextmanager
from typing import Optional, Type, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.engine import Result
from app.core.db_utils import supports_for_update

logger = logging.getLogger(__name__)

ExceptionT = TypeVar("ExceptionT", bound=BaseException)


@asynccontextmanager
async def transactional_session(
    db: AsyncSession,
    *,
    auto_commit: bool = True,
    reraise: bool = True,
    log_errors: bool = True,
    error_message: Optional[str] = None,
    exception_type: Optional[Type[ExceptionT]] = None,
):
    """
    Context manager for database transactions with automatic commit/rollback.

    This utility eliminates the repetitive pattern of:
        try:
            # database operations
            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(...)
            raise

    Usage:
        # Basic usage (auto-commit, auto-rollback on error)
        async with transactional_session(db):
            db.add(obj)

        # Without auto-commit (manual commit control)
        async with transactional_session(db, auto_commit=False):
            db.add(obj)
            await db.commit()  # Manual commit

        # Suppress exceptions (useful for non-critical operations)
        async with transactional_session(db, reraise=False):
            db.add(obj)

        # Custom error message
        async with transactional_session(db, error_message="Failed to create user"):
            db.add(user)

        # Convert exceptions to HTTP exceptions
        from fastapi import HTTPException
        async with transactional_session(db, exception_type=HTTPException):
            db.add(obj)

    Args:
        db: Database session
        auto_commit: Whether to automatically commit on successful exit (default: True)
        reraise: Whether to re-raise exceptions after rollback (default: True)
        log_errors: Whether to log errors (default: True)
        error_message: Custom error message for logging (default: None)
        exception_type: Exception type to raise instead of original (default: None)

    Yields:
        AsyncSession: The database session for use within the context

    Raises:
        Exception: Re-raises the original exception (or converted type) if reraise=True
    """
    try:
        yield db

        # Auto-commit on successful exit
        if auto_commit:
            await db.commit()

    except Exception as e:
        # Always rollback on error
        await db.rollback()

        # Log error if requested
        if log_errors:
            if error_message:
                logger.exception("%s: %s", error_message, str(e))
            else:
                logger.exception("Database transaction failed: %s", str(e))

        # Re-raise if requested
        if reraise:
            if exception_type:
                if issubclass(exception_type, HTTPException):
                    raise exception_type(status_code=400, detail=str(e))
                raise exception_type(str(e))
            else:
                # Re-raise original exception
                raise


async def execute_with_lock(
    db: AsyncSession,
    query: Select,
) -> Result:
    """
    Execute a query with row-level locking if the database supports it.

    This utility eliminates the repetitive pattern of:
        sel = select(Model).where(...)
        if supports_for_update(db):
            sel = sel.with_for_update()
        result = await db.execute(sel)

    Usage:
        # Basic usage
        sel = select(User).where(User.username == username)
        result = await execute_with_lock(db, sel)
        user = result.scalar_one_or_none()

        # With complex query
        query = select(Project).where(
            Project.jira_key == jira_key
        ).where(Project.id != project_id)
        result = await execute_with_lock(db, query)
        if result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Duplicate")

    Args:
        db: Database session
        query: SQLAlchemy Select query to execute

    Returns:
        Result: The query execution result (use .scalar_one_or_none(), .scalars().all(), etc.)
    """
    if supports_for_update(db):
        query = query.with_for_update()
    return await db.execute(query)
