"""Query duration metrics using SQLAlchemy event system.

This module instruments SQLAlchemy to track database query execution times.
It uses contextvars to associate queries with their originating endpoints.

Usage:
    # In middleware, set the context for each request
    from app.core.query_metrics import set_query_context
    set_query_context(request.url.path)

    # Register events on engine startup
    from app.core.query_metrics import register_query_events
    register_query_events(engine.sync_engine)
"""

from __future__ import annotations

import time
import logging
from contextvars import ContextVar
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.core.metrics import metrics

logger = logging.getLogger(__name__)

# Context variable to track current endpoint/operation
_query_context: ContextVar[str] = ContextVar("query_context", default="unknown")

# Thread-local storage for query start times (keyed by connection id + cursor id)
_query_start_times: dict[int, float] = {}


def set_query_context(endpoint: str) -> None:
    """Set the current query context (typically the endpoint path).

    Args:
        endpoint: The endpoint path or operation name for labeling metrics
    """
    # Normalize endpoint path for metrics (remove IDs, keep structure)
    normalized = _normalize_endpoint(endpoint)
    _query_context.set(normalized)


def get_query_context() -> str:
    """Get the current query context."""
    return _query_context.get()


def _normalize_endpoint(path: str) -> str:
    """Normalize endpoint path for metrics aggregation.

    Replaces numeric IDs with {id} to group similar endpoints together.
    e.g., /api/v1/tasks/123 -> /api/v1/tasks/{id}

    Args:
        path: Raw endpoint path

    Returns:
        Normalized path for metrics labeling
    """
    if not path:
        return "unknown"

    parts = path.split("/")
    normalized_parts = []

    for part in parts:
        if part.isdigit():
            normalized_parts.append("{id}")
        elif part and len(part) > 20 and all(c.isalnum() or c == "-" for c in part):
            # Likely a UUID or hash
            normalized_parts.append("{uuid}")
        else:
            normalized_parts.append(part)

    return "/".join(normalized_parts)


def _before_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    """SQLAlchemy event handler called before query execution.

    Records the start time for timing the query.
    """
    # Use cursor id as key (unique per query execution)
    key = id(cursor)
    _query_start_times[key] = time.perf_counter()


def _after_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    """SQLAlchemy event handler called after query execution.

    Calculates duration and records the metric.
    """
    key = id(cursor)
    start_time = _query_start_times.pop(key, None)

    if start_time is None:
        return

    duration = time.perf_counter() - start_time
    endpoint = get_query_context()

    # Record the observation
    try:
        metrics.observe("db_query_duration_seconds", duration, labels={"endpoint": endpoint})

        # Also track slow queries (> 1 second) separately
        if duration > 1.0:
            metrics.inc("db_slow_query_total", labels={"endpoint": endpoint})
            # Log slow queries for debugging
            logger.warning(
                "Slow query detected: %.3fs on %s - %s",
                duration,
                endpoint,
                statement[:200] if statement else "unknown",
            )

    except Exception as e:
        # Don't let metrics collection break the application
        logger.debug("Failed to record query metrics: %s", e)


def _handle_error(
    exception_context: Any,
) -> None:
    """SQLAlchemy event handler for query errors.

    Cleans up timing state and records error metrics.
    """
    try:
        cursor = getattr(exception_context, "cursor", None)
        if cursor:
            key = id(cursor)
            _query_start_times.pop(key, None)

        endpoint = get_query_context()
        metrics.inc("db_query_error_total", labels={"endpoint": endpoint})
    except Exception as e:
        logger.debug("Failed to record query error metric: %s", e)


def register_query_events(engine: Engine) -> None:
    """Register query timing events on a SQLAlchemy engine.

    Should be called once per engine during application startup.

    Args:
        engine: SQLAlchemy Engine instance (sync engine, not async)
    """
    # Check if already registered to avoid duplicate handlers
    if hasattr(engine, "_query_metrics_registered"):
        return

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    event.listen(engine, "handle_error", _handle_error)

    # Mark as registered
    engine._query_metrics_registered = True  # type: ignore[attr-defined]

    logger.info("Query duration metrics registered for engine: %s", engine.url)


def get_query_stats() -> dict[str, Any]:
    """Get current query statistics from metrics.

    Returns:
        Dictionary with query count, duration stats by endpoint
    """
    # This provides a summary view of collected metrics
    stats: dict[str, Any] = {
        "pending_queries": len(_query_start_times),
    }
    return stats
