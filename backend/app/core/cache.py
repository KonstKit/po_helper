"""
Redis cache client for background tasks.
Provides shared Redis connection for Celery tasks and SSE notifications.
"""

import logging
from typing import Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Redis client instance
redis_client: Optional[object] = None

try:
    if settings.REDIS_URL:
        import redis

        redis_client = redis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=5, socket_timeout=5
        )
        # Test connection
        redis_client.ping()
        logger.info("Redis client initialized for background tasks")
except ImportError:
    logger.warning("Redis package not installed, pub/sub notifications disabled")
    redis_client = None
except Exception as e:
    logger.warning(f"Redis connection failed, pub/sub notifications disabled: {e}")
    redis_client = None
