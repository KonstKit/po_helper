"""
Cache service for storing and retrieving expensive operation results.
Supports both in-memory and Redis caching with TTL.
"""
from typing import Any, Optional, Dict
import json
import time
import logging
from functools import wraps
from app.core.config import settings
import hashlib

logger = logging.getLogger(__name__)

class CacheService:
    def __init__(self):
        self._memory_cache: Dict[str, tuple[Any, float]] = {}
        self._redis_client = None
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection if available."""
        try:
            if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
                try:
                    import redis
                    self._redis_client = redis.from_url(
                        settings.REDIS_URL,
                        decode_responses=True,
                        socket_connect_timeout=2,
                        socket_timeout=2
                    )
                    # Test connection
                    self._redis_client.ping()
                    logger.info("Redis cache initialized successfully")
                except ImportError:
                    logger.info("Redis package not installed, using memory cache")
                    self._redis_client = None
        except Exception as e:
            logger.warning(f"Redis cache initialization failed, falling back to memory cache: {e}")
            self._redis_client = None

    def _make_key(self, prefix: str, *args, **kwargs) -> str:
        """Generate a cache key from prefix and arguments."""
        # Create a stable hash from arguments
        key_data = f"{prefix}:{str(args)}:{str(sorted(kwargs.items()))}"
        key_hash = hashlib.md5(key_data.encode()).hexdigest()[:12]
        return f"po_helper:{prefix}:{key_hash}"

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not hasattr(settings, 'JIRA_CACHE_ENABLED') or not settings.JIRA_CACHE_ENABLED:
            return None

        # Try Redis first
        if self._redis_client:
            try:
                value = self._redis_client.get(key)
                if value:
                    return json.loads(value)
            except Exception as e:
                logger.debug(f"Redis get failed for {key}: {e}")

        # Fallback to memory cache
        if key in self._memory_cache:
            value, expiry = self._memory_cache[key]
            if time.time() < expiry:
                return value
            else:
                # Clean up expired entry
                del self._memory_cache[key]

        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache with optional TTL."""
        if not hasattr(settings, 'JIRA_CACHE_ENABLED') or not settings.JIRA_CACHE_ENABLED:
            return False

        ttl = ttl or getattr(settings, 'JIRA_CACHE_TTL', 300)

        # Try Redis first
        if self._redis_client:
            try:
                self._redis_client.setex(key, ttl, json.dumps(value))
                return True
            except Exception as e:
                logger.debug(f"Redis set failed for {key}: {e}")

        # Fallback to memory cache
        expiry = time.time() + ttl
        self._memory_cache[key] = (value, expiry)

        # Clean up old entries (keep max 1000 entries)
        if len(self._memory_cache) > 1000:
            self._cleanup_memory_cache()

        return True

    def delete(self, key: str) -> bool:
        """Delete value from cache."""
        deleted = False

        # Try Redis
        if self._redis_client:
            try:
                deleted = bool(self._redis_client.delete(key))
            except Exception as e:
                logger.debug(f"Redis delete failed for {key}: {e}")

        # Also delete from memory cache
        if key in self._memory_cache:
            del self._memory_cache[key]
            deleted = True

        return deleted

    def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern."""
        count = 0

        # Clear from Redis
        if self._redis_client:
            try:
                for key in self._redis_client.scan_iter(match=f"po_helper:{pattern}*"):
                    self._redis_client.delete(key)
                    count += 1
            except Exception as e:
                logger.debug(f"Redis clear pattern failed for {pattern}: {e}")

        # Clear from memory cache
        keys_to_delete = [k for k in self._memory_cache.keys() if k.startswith(f"po_helper:{pattern}")]
        for key in keys_to_delete:
            del self._memory_cache[key]
            count += 1

        return count

    def _cleanup_memory_cache(self):
        """Remove expired entries from memory cache."""
        current_time = time.time()
        expired_keys = [k for k, (_, expiry) in self._memory_cache.items() if expiry <= current_time]
        for key in expired_keys:
            del self._memory_cache[key]

        # If still too many, remove oldest entries
        if len(self._memory_cache) > 800:
            sorted_items = sorted(self._memory_cache.items(), key=lambda x: x[1][1])
            for key, _ in sorted_items[:200]:
                del self._memory_cache[key]


# Global cache instance
cache_service = CacheService()


def cached(prefix: str, ttl: Optional[int] = None):
    """Decorator to cache function results."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = cache_service._make_key(prefix, *args, **kwargs)

            # Try to get from cache
            cached_value = cache_service.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {prefix}")
                return cached_value

            # Call function and cache result
            result = func(*args, **kwargs)
            if result is not None:
                cache_service.set(cache_key, result, ttl)

            return result

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Generate cache key
            cache_key = cache_service._make_key(prefix, *args, **kwargs)

            # Try to get from cache
            cached_value = cache_service.get(cache_key)
            if cached_value is not None:
                logger.debug(f"Cache hit for {prefix}")
                return cached_value

            # Call function and cache result
            result = await func(*args, **kwargs)
            if result is not None:
                cache_service.set(cache_key, result, ttl)

            return result

        # Return appropriate wrapper based on function type
        if hasattr(func, '__aiter__') or hasattr(func, '__await__'):
            return async_wrapper
        else:
            return wrapper

    return decorator