"""Application-wide rate limiting helpers."""

from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Use swallow_errors to prevent rate limiter backend glitches from breaking requests.
# Default per-endpoint limits are opt-in via @limiter.limit (backfill, etc.).
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],  # rely on explicit decorators instead of global limit
    headers_enabled=True,
    auto_check=True,
    swallow_errors=True,
)

__all__ = [
    "limiter",
    "RateLimitExceeded",
    "_rate_limit_exceeded_handler",
]
