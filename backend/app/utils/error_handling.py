"""API error handling utilities for consistent exception management."""

import logging
from contextlib import contextmanager, asynccontextmanager
from typing import Optional, Dict, Any, Type

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# Exception type to HTTP status code mapping
EXCEPTION_STATUS_CODES: Dict[str, int] = {
    "JiraAuthError": 401,
    "JiraUnexpectedResponse": 502,
    "ConfluenceAuthError": 401,
    "GitHubAuthError": 401,
    "GitLabAuthError": 401,
    "NotFoundError": 404,
    "ValidationError": 400,
    "PermissionError": 403,
    "TimeoutError": 504,
    # Database errors
    "SQLAlchemyError": 500,
    "IntegrityError": 409,
    "NoResultFound": 404,
}


@contextmanager
def handle_api_error(
    *,
    operation: Optional[str] = None,
    status_code: int = 400,
    context: Optional[Dict[str, Any]] = None,
    log_level: str = "error",
    exception_map: Optional[Dict[Type[Exception], int]] = None,
):
    """
    Context manager for consistent API error handling with logging.

    Eliminates the repetitive pattern of:
        try:
            # API operation
        except SpecificError as e:
            logger.error("message: %s", str(e))
            raise HTTPException(status_code=401, detail=str(e))
        except Exception as e:
            logger.error("message: %s", str(e))
            raise HTTPException(status_code=400, detail=str(e))

    Usage:
        # Basic usage
        with handle_api_error(operation="fetch_jira_projects"):
            result = jira_service.list_projects()

        # With custom status code
        with handle_api_error(operation="create_user", status_code=500):
            db.add(user)

        # With context data for logging
        with handle_api_error(
            operation="sync_confluence",
            context={"project_id": 123, "page_count": 50}
        ):
            confluence_service.sync_pages()

        # With exception mapping
        with handle_api_error(
            operation="authenticate",
            exception_map={
                JiraAuthError: 401,
                JiraUnexpectedResponse: 502,
            }
        ):
            jira_service.connect()

    Args:
        operation: Name of the operation for logging (e.g., "fetch_projects")
        status_code: Default HTTP status code for unmapped exceptions (default: 400)
        context: Additional context data to include in logs (e.g., {"project_id": 123})
        log_level: Logging level - "error", "warning", "exception" (default: "error")
        exception_map: Mapping of specific exception types to HTTP status codes

    Raises:
        HTTPException: Always raises FastAPI HTTPException with appropriate status code
    """
    try:
        yield

    except HTTPException:
        # Re-raise HTTPException as-is (already formatted)
        raise

    except Exception as e:
        exception_type = type(e).__name__

        # Determine HTTP status code
        http_status = status_code

        # Check custom exception map first
        if exception_map:
            for exc_type, code in exception_map.items():
                if isinstance(e, exc_type):
                    http_status = code
                    break

        # Check default exception mapping
        if http_status == status_code and exception_type in EXCEPTION_STATUS_CODES:
            http_status = EXCEPTION_STATUS_CODES[exception_type]

        # Build log message
        log_parts = []
        if operation:
            log_parts.append(f"{operation}.error")

        if context:
            context_str = " ".join(f"{k}={v}" for k, v in context.items())
            log_parts.append(context_str)

        log_message = " ".join(log_parts) if log_parts else "API operation failed"

        # Log with appropriate level
        if log_level == "exception":
            logger.exception("%s: %s (%s)", log_message, str(e), exception_type)
        elif log_level == "warning":
            logger.warning("%s: %s (%s)", log_message, str(e), exception_type)
        else:  # error
            logger.error("%s: %s (%s)", log_message, str(e), exception_type, exc_info=True)

        # Raise HTTPException
        detail = str(e) if str(e) else f"{exception_type} occurred"
        raise HTTPException(status_code=http_status, detail=detail)


@asynccontextmanager
async def async_handle_api_error(
    *,
    operation: Optional[str] = None,
    status_code: int = 500,
    context: Optional[Dict[str, Any]] = None,
    log_level: str = "error",
    exception_map: Optional[Dict[Type[Exception], int]] = None,
    db_session=None,
):
    """
    Async context manager for API error handling with optional DB rollback.

    Same as handle_api_error but supports async operations and automatic
    database session rollback on error.

    Usage:
        async with async_handle_api_error(
            operation="create_user",
            db_session=db
        ):
            db.add(user)
            await db.commit()

    Args:
        operation: Name of the operation for logging
        status_code: Default HTTP status code for unmapped exceptions (default: 500)
        context: Additional context data to include in logs
        log_level: Logging level - "error", "warning", "exception"
        exception_map: Mapping of specific exception types to HTTP status codes
        db_session: Optional AsyncSession to rollback on error
    """
    try:
        yield

    except HTTPException:
        raise

    except Exception as e:
        # Rollback DB session if provided
        if db_session is not None:
            try:
                await db_session.rollback()
            except Exception as rollback_err:
                logger.warning("Failed to rollback session: %s", rollback_err)

        exception_type = type(e).__name__

        # Determine HTTP status code
        http_status = status_code

        if exception_map:
            for exc_type, code in exception_map.items():
                if isinstance(e, exc_type):
                    http_status = code
                    break

        if http_status == status_code and exception_type in EXCEPTION_STATUS_CODES:
            http_status = EXCEPTION_STATUS_CODES[exception_type]

        # Build log message
        log_parts = []
        if operation:
            log_parts.append(f"{operation}.error")

        if context:
            context_str = " ".join(f"{k}={v}" for k, v in context.items())
            log_parts.append(context_str)

        log_message = " ".join(log_parts) if log_parts else "API operation failed"

        if log_level == "exception":
            logger.exception("%s: %s (%s)", log_message, str(e), exception_type)
        elif log_level == "warning":
            logger.warning("%s: %s (%s)", log_message, str(e), exception_type)
        else:
            logger.error("%s: %s (%s)", log_message, str(e), exception_type, exc_info=True)

        detail = str(e) if str(e) else f"{exception_type} occurred"
        raise HTTPException(status_code=http_status, detail=detail)
