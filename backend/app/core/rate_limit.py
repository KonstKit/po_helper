"""Application-wide rate limiting helpers."""

from __future__ import annotations

import logging
from typing import Optional

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings

logger = logging.getLogger(__name__)


def _resolve_storage_uri() -> Optional[str]:
    """Use Redis-backed counters when a broker is reachable.

    In-memory storage (the slowapi default) keeps per-process counters:
    with multiple workers the effective limit multiplies, and a shared
    limit is impossible. Redis makes limits global; when it is not
    reachable we degrade to in-memory with a loud warning.
    """
    url = settings.REDIS_URL
    if not url:
        return None
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        client.close()
        return url
    except Exception as exc:
        logger.warning(
            "Rate limiter Redis storage unavailable (%s); falling back to "
            "in-memory per-process counters - effective limits multiply by "
            "the worker count",
            exc,
        )
        return None


# Use swallow_errors to prevent rate limiter backend glitches from breaking requests.
# Default per-endpoint limits are opt-in via @limiter.limit (backfill, etc.).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],  # rely on explicit decorators instead of global limit
    headers_enabled=True,
    auto_check=True,
    swallow_errors=True,
    storage_uri=_resolve_storage_uri(),
)

__all__ = [
    "limiter",
    "RateLimitExceeded",
    "_rate_limit_exceeded_handler",
]
