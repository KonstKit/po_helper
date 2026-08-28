"""
Enhanced Redis caching service with tiered TTL policies, cache key patterns,
and intelligent invalidation for FastAPI + async SQLAlchemy applications.

This module provides:
1. Tiered caching with different TTLs by data volatility
2. Structured cache key patterns for predictable invalidation
3. Cache-aside pattern with async support
4. Batch invalidation utilities
5. Cache warming strategies
"""

from __future__ import annotations

import asyncio
import secrets
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from app.core.metrics import metrics

aioredis: Any | None
try:
    import redis.asyncio as aioredis

    REDIS_ASYNC_AVAILABLE = True
except ImportError:
    aioredis = None
    REDIS_ASYNC_AVAILABLE = False

redis: Any | None
try:
    import redis

    REDIS_SYNC_AVAILABLE = True
except ImportError:
    redis = None
    REDIS_SYNC_AVAILABLE = False

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =============================================================================
# Cache TTL Policies - Tiered by data volatility
# =============================================================================


class CacheTier(Enum):
    """Cache tiers based on data volatility and computation cost."""

    # Real-time data - very short TTL (10-30 seconds)
    # Use for: Active sprint status, WIP limits, live metrics
    REALTIME = "realtime"

    # Frequently changing data - short TTL (1-5 minutes)
    # Use for: Task lists, sprint burndown, team health
    HOT = "hot"

    # Moderately stable data - medium TTL (5-15 minutes)
    # Use for: Velocity trends, DORA metrics, project sprints
    WARM = "warm"

    # Rarely changing data - long TTL (30-60 minutes)
    # Use for: Historical analytics, completed sprint data
    COLD = "cold"

    # Static/computed data - very long TTL (1-24 hours)
    # Use for: Traceability matrix, forecast calculations
    STATIC = "static"


@dataclass
class CacheTierConfig:
    """Configuration for each cache tier."""

    ttl_seconds: int
    stale_while_revalidate: int  # Serve stale while fetching fresh
    max_entries: int  # LRU eviction threshold
    compress: bool  # Enable compression for large values


TTL_POLICIES: Dict[CacheTier, CacheTierConfig] = {
    CacheTier.REALTIME: CacheTierConfig(
        ttl_seconds=15, stale_while_revalidate=5, max_entries=1000, compress=False
    ),
    CacheTier.HOT: CacheTierConfig(
        ttl_seconds=60, stale_while_revalidate=30, max_entries=5000, compress=False
    ),
    CacheTier.WARM: CacheTierConfig(
        ttl_seconds=300,  # 5 minutes
        stale_while_revalidate=60,
        max_entries=10000,
        compress=True,
    ),
    CacheTier.COLD: CacheTierConfig(
        ttl_seconds=1800,  # 30 minutes
        stale_while_revalidate=300,
        max_entries=50000,
        compress=True,
    ),
    CacheTier.STATIC: CacheTierConfig(
        ttl_seconds=3600,  # 1 hour
        stale_while_revalidate=600,
        max_entries=100000,
        compress=True,
    ),
}


# =============================================================================
# Cache Key Patterns - Structured for predictable invalidation
# =============================================================================


class CacheKeyBuilder:
    """
    Structured cache key builder for consistent key patterns.

    Key Format: {prefix}:{domain}:{resource}:{id}:{variant}

    Examples:
        - analytics:project:123:velocity:sprints_5
        - analytics:sprint:456:burndown
        - traceability:project:123:matrix
        - tasks:project:123:list:skip_0_limit_100
    """

    PREFIX = "po_helper"
    SEPARATOR = ":"

    @classmethod
    def build(
        cls,
        domain: str,
        resource: str,
        resource_id: Union[int, str],
        variant: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Build a structured cache key."""
        parts = [cls.PREFIX, domain, resource, str(resource_id)]

        if variant:
            parts.append(variant)

        # Add sorted kwargs as variant if present
        if kwargs:
            sorted_kwargs = sorted(kwargs.items())
            variant_hash = hashlib.md5(str(sorted_kwargs).encode()).hexdigest()[:8]
            parts.append(variant_hash)

        return cls.SEPARATOR.join(parts)

    @classmethod
    def pattern_for_invalidation(
        cls,
        domain: str,
        resource: Optional[str] = None,
        resource_id: Optional[Union[int, str]] = None,
    ) -> str:
        """
        Build a pattern for bulk invalidation using Redis SCAN.

        Examples:
            - Invalidate all project 123 cache: pattern_for_invalidation("analytics", "project", 123)
            - Invalidate all analytics: pattern_for_invalidation("analytics")
        """
        parts = [cls.PREFIX, domain]

        if resource:
            parts.append(resource)
        if resource_id is not None:
            parts.append(str(resource_id))

        return cls.SEPARATOR.join(parts) + "*"


# =============================================================================
# Cache Key Definitions by Domain
# =============================================================================


class AnalyticsCacheKeys:
    """Cache key builders for analytics endpoints."""

    @staticmethod
    def velocity(project_id: int, sprints_count: int = 5) -> str:
        return CacheKeyBuilder.build(
            "analytics", "project", project_id, variant=f"velocity_sprints_{sprints_count}"
        )

    @staticmethod
    def dora(project_id: int, window_days: int = 30) -> str:
        return CacheKeyBuilder.build(
            "analytics", "project", project_id, variant=f"dora_days_{window_days}"
        )

    @staticmethod
    def team_health(project_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "project", project_id, variant="team_health")

    @staticmethod
    def budget_hours(project_id: int, top_n: int = 5) -> str:
        return CacheKeyBuilder.build(
            "analytics", "project", project_id, variant=f"budget_hours_top_{top_n}"
        )

    @staticmethod
    def sprint_burndown(sprint_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "sprint", sprint_id, variant="burndown")

    @staticmethod
    def sprint_capacity(sprint_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "sprint", sprint_id, variant="capacity")

    @staticmethod
    def sprint_wip(sprint_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "sprint", sprint_id, variant="wip")

    @staticmethod
    def project_sprints(project_id: int, limit: int, board_id: Optional[int]) -> str:
        return CacheKeyBuilder.build(
            "analytics",
            "project",
            project_id,
            variant="sprints",
            limit=limit,
            board_id=board_id or 0,
        )

    @staticmethod
    def project_risks(project_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "project", project_id, variant="risks")

    @staticmethod
    def project_forecast(project_id: int) -> str:
        return CacheKeyBuilder.build("analytics", "project", project_id, variant="forecast")

    @staticmethod
    def project_burndown(project_id: int, sprint_id: Optional[int] = None) -> str:
        return CacheKeyBuilder.build(
            "analytics", "project", project_id, variant=f"burndown_sprint_{sprint_id or 0}"
        )

    @staticmethod
    def test_trend(project_id: Optional[int], days: int) -> str:
        """Cache key for test trend data."""
        pid: int | str = project_id if project_id is not None else "global"
        return CacheKeyBuilder.build(
            "analytics", "test_trend", pid, variant=f"project_{project_id or 0}_days_{days}"
        )

    @staticmethod
    def coverage_trend(project_id: Optional[int], days: int) -> str:
        """Cache key for coverage trend data."""
        pid: int | str = project_id if project_id is not None else "global"
        return CacheKeyBuilder.build(
            "analytics", "coverage_trend", pid, variant=f"project_{project_id or 0}_days_{days}"
        )


class CapacityCacheKeys:
    """Cache key builders for capacity endpoints."""

    @staticmethod
    def team_summary(project_id: int) -> str:
        """Cache key for team capacity summary."""
        return CacheKeyBuilder.build("capacity", "project", project_id, variant="team_summary")

    @staticmethod
    def cfd_data(project_id: int) -> str:
        """Cache key for CFD (Cumulative Flow Diagram) data."""
        return CacheKeyBuilder.build("capacity", "project", project_id, variant="cfd_data")

    @staticmethod
    def flow_metrics(project_id: int) -> str:
        """Cache key for flow metrics."""
        return CacheKeyBuilder.build("capacity", "project", project_id, variant="flow_metrics")

    @staticmethod
    def health_summary(project_id: int) -> str:
        """Cache key for team health summary."""
        return CacheKeyBuilder.build("capacity", "project", project_id, variant="health_summary")


class TraceabilityCacheKeys:
    """Cache key builders for traceability endpoints."""

    @staticmethod
    def matrix(project_id: Optional[int]) -> str:
        pid: int | str = project_id if project_id is not None else "global"
        return CacheKeyBuilder.build("traceability", "project", pid, variant="matrix")

    @staticmethod
    def rtm_matrix(
        project_id: Optional[int],
        row_types: Optional[str] = None,
        col_types: Optional[str] = None,
        row_skip: int = 0,
        row_limit: int = 50,
        # Additional filter parameters to prevent cache collisions
        col_skip: int = 0,
        col_limit: int = 50,
        row_statuses: Optional[str] = None,
        col_statuses: Optional[str] = None,
        link_types: Optional[str] = None,
        min_confidence: float = 0.0,
        direction: str = "both",
        search_query: Optional[str] = None,
        include_orphans: bool = False,
    ) -> str:
        """Cache key for RTM matrix with ALL filters to prevent collisions."""
        pid: int | str = project_id if project_id is not None else "global"
        # Create a deterministic hash of all filter parameters
        filter_parts = [
            f"rt_{row_types or 'all'}",
            f"ct_{col_types or 'all'}",
            f"rs_{row_skip}",
            f"rl_{row_limit}",
            f"cs_{col_skip}",
            f"cl_{col_limit}",
            f"rsts_{row_statuses or 'all'}",
            f"csts_{col_statuses or 'all'}",
            f"lt_{link_types or 'all'}",
            f"mc_{min_confidence:.3f}",
            f"dir_{direction}",
            f"sq_{search_query or ''}",
            f"io_{include_orphans}",
        ]
        filter_hash = hashlib.md5("_".join(filter_parts).encode()).hexdigest()[:12]
        return CacheKeyBuilder.build(
            "traceability",
            "rtm_matrix",
            pid,
            variant=f"f_{filter_hash}",
        )

    @staticmethod
    def coverage_analytics(
        project_id: Optional[int],
        include_trends: bool = False,
        artifact_types: Optional[str] = None,
        trend_days: int = 30,
    ) -> str:
        """Cache key for coverage analytics with ALL parameters to prevent collisions."""
        pid: int | str = project_id if project_id is not None else "global"
        # Include all parameters in cache key
        parts = [
            f"trends_{include_trends}",
            f"types_{artifact_types or 'req'}",
            f"days_{trend_days}",
        ]
        variant_hash = hashlib.md5("_".join(parts).encode()).hexdigest()[:8]
        return CacheKeyBuilder.build(
            "traceability",
            "coverage",
            pid,
            variant=f"v_{variant_hash}",
        )

    @staticmethod
    def matrix_configs(project_id: Optional[int]) -> str:
        """Cache key for matrix configurations list."""
        pid: int | str = project_id if project_id is not None else "global"
        return CacheKeyBuilder.build("traceability", "matrix_configs", pid)

    @staticmethod
    def flow(artifact_id: int, depth: int) -> str:
        return CacheKeyBuilder.build(
            "traceability", "artifact", artifact_id, variant=f"flow_depth_{depth}"
        )

    @staticmethod
    def task_artifacts(jira_key: str) -> str:
        return CacheKeyBuilder.build("traceability", "task", jira_key, variant="artifacts")

    @staticmethod
    def full_chain(artifact_id: int, depth: int, direction: str, min_confidence: float) -> str:
        """Cache key for full traceability chain (bidirectional BFS)."""
        return CacheKeyBuilder.build(
            "traceability",
            "chain",
            artifact_id,
            variant=f"depth_{depth}_{direction}_conf_{min_confidence:.3f}",
        )

    @staticmethod
    def impact_analysis(artifact_id: int, change_type: str) -> str:
        """Cache key for impact analysis results."""
        return CacheKeyBuilder.build(
            "traceability", "impact", artifact_id, variant=f"change_{change_type}"
        )

    @staticmethod
    def orphaned_artifacts(
        project_id: Optional[int], artifact_type: Optional[str], skip: int = 0, limit: int = 100
    ) -> str:
        """Cache key for orphaned artifacts query."""
        pid: int | str = project_id if project_id is not None else "global"
        atype = artifact_type if artifact_type else "all"
        return CacheKeyBuilder.build(
            "traceability", "orphans", pid, variant=f"type_{atype}_skip_{skip}_limit_{limit}"
        )


class TasksCacheKeys:
    """Cache key builders for tasks endpoints."""

    @staticmethod
    def list_key(
        project_id: Optional[int] = None,
        sprint_id: Optional[int] = None,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> str:
        return CacheKeyBuilder.build(
            "tasks",
            "list",
            "query",
            project_id=project_id or 0,
            sprint_id=sprint_id or 0,
            status=status or "",
            assignee=assignee or "",
            skip=skip,
            limit=limit,
        )


class JiraCacheKeys:
    """Cache key builders for JIRA API responses."""

    @staticmethod
    def project(project_key: str) -> str:
        """Cache key for JIRA project details."""
        return CacheKeyBuilder.build("jira", "project", project_key, variant="details")

    @staticmethod
    def project_list(query: Optional[str] = None) -> str:
        """Cache key for JIRA projects list."""
        return CacheKeyBuilder.build("jira", "projects", "list", variant=f"query_{query or 'all'}")

    @staticmethod
    def boards(project_key: str) -> str:
        """Cache key for JIRA boards list."""
        return CacheKeyBuilder.build("jira", "boards", project_key)

    @staticmethod
    def sprints(board_id: int) -> str:
        """Cache key for JIRA sprints list."""
        return CacheKeyBuilder.build("jira", "sprints", board_id)

    @staticmethod
    def sprint_issues(sprint_id: int) -> str:
        """Cache key for JIRA sprint issues."""
        return CacheKeyBuilder.build("jira", "sprint_issues", sprint_id)

    @staticmethod
    def worklogs(issue_key: str) -> str:
        """Cache key for JIRA issue worklogs."""
        return CacheKeyBuilder.build("jira", "worklogs", issue_key)


class QualityCacheKeys:
    """Cache key builders for quality endpoints."""

    @staticmethod
    def summary(project_id: int, sprint_id: Optional[int] = None) -> str:
        return CacheKeyBuilder.build(
            "quality", "project", project_id, variant=f"summary_sprint_{sprint_id or 0}"
        )

    @staticmethod
    def dashboard(project_id: int, sprint_id: Optional[int] = None) -> str:
        return CacheKeyBuilder.build(
            "quality", "project", project_id, variant=f"dashboard_sprint_{sprint_id or 0}"
        )

    @staticmethod
    def component_analysis(project_id: int, sprint_id: Optional[int] = None) -> str:
        return CacheKeyBuilder.build(
            "quality", "project", project_id, variant=f"components_sprint_{sprint_id or 0}"
        )

    @staticmethod
    def trend(project_id: int, days: int = 30) -> str:
        return CacheKeyBuilder.build("quality", "project", project_id, variant=f"trend_days_{days}")

    @staticmethod
    def history(project_id: int, limit: int = 100) -> str:
        return CacheKeyBuilder.build(
            "quality", "project", project_id, variant=f"history_limit_{limit}"
        )

    @staticmethod
    def root_cause_analysis(project_id: int, sprint_id: Optional[int] = None) -> str:
        return CacheKeyBuilder.build(
            "quality", "project", project_id, variant=f"root_cause_sprint_{sprint_id or 0}"
        )


# =============================================================================
# Enhanced Cache Service with Async Support
# =============================================================================


class EnhancedCacheService:
    """
    Production-grade cache service with:
    - Tiered TTL policies
    - Async Redis support
    - In-memory fallback
    - Stale-while-revalidate pattern
    - Batch invalidation
    """

    _MAX_PER_KEY_LOCKS = 10_000
    _FLIGHT_LEASE_SECONDS = 10
    _FLIGHT_POLL_INTERVAL = 0.1
    _FLIGHT_POLLS = 50

    def __init__(self, redis_url: Optional[str] = None):
        self._redis_url = redis_url
        self._async_redis: Optional[Any] = None
        self._sync_redis: Optional[Any] = None
        self._memory_cache: Dict[str, tuple[Any, float, float]] = {}  # value, expiry, stale_expiry
        self._locks: Dict[str, asyncio.Lock] = {}
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize async Redis connection."""
        if self._initialized:
            return True

        if self._redis_url and REDIS_ASYNC_AVAILABLE and aioredis is not None:
            try:
                self._async_redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                await self._async_redis.ping()
                logger.info("Async Redis cache initialized")
                self._initialized = True
                return True
            except Exception as e:
                logger.warning(f"Async Redis initialization failed: {e}")
                self._async_redis = None

        logger.info("Using in-memory cache fallback")
        self._initialized = True
        return True

    def _get_tier_config(self, tier: CacheTier) -> CacheTierConfig:
        """Get configuration for cache tier."""
        return TTL_POLICIES.get(tier, TTL_POLICIES[CacheTier.HOT])

    async def get(self, key: str, tier: CacheTier = CacheTier.HOT) -> Optional[Any]:
        """
        Get value from cache.

        Returns None if not found or expired.
        """
        await self.initialize()

        # Extract cache type from key for metrics
        cache_type = key.split(":")[1] if ":" in key else "async"

        # Try Redis first
        if self._async_redis:
            try:
                value = await self._async_redis.get(key)
                if value:
                    metrics.inc("cache_hits_total", labels={"type": cache_type})
                    return json.loads(value)
            except Exception as e:
                logger.warning("Redis cache get degraded to memory (key=%s): %s", key, e)

        # Fallback to memory cache
        if key in self._memory_cache:
            value, expiry, stale_expiry = self._memory_cache[key]
            now = time.time()
            if now < expiry:
                metrics.inc("cache_hits_total", labels={"type": cache_type})
                return value
            elif now < stale_expiry:
                # Return stale value (caller should trigger background refresh)
                metrics.inc("cache_hits_total", labels={"type": cache_type})
                return value
            else:
                del self._memory_cache[key]

        metrics.inc("cache_misses_total", labels={"type": cache_type})
        return None

    async def get_or_set(
        self, key: str, factory: Callable[[], Any], tier: CacheTier = CacheTier.HOT
    ) -> Any:
        """
        Get from cache or compute and store.

        Implements cache-aside pattern with lock to prevent thundering herd.
        """
        # Check cache first
        cached = await self.get(key, tier)
        if cached is not None:
            return cached

        # Get or create lock for this key. The dict is bounded: an unused,
        # uncontended lock is removed right away, and a hard cap protects
        # against pathological key cardinality (a stale entry is simply
        # replaced - waiters keep their own reference).
        lock = self._locks.get(key)
        if lock is None:
            if len(self._locks) >= self._MAX_PER_KEY_LOCKS:
                self._locks = {k: v for k, v in self._locks.items() if v.locked() or k == key}
            lock = self._locks.get(key) or asyncio.Lock()
            self._locks[key] = lock

        # Cross-process single-flight: with several workers the local lock
        # alone still lets one rebuild per process. Try to hold a short
        # Redis lease; losers poll briefly for the winner's value and fall
        # back to computing themselves after the lease window (degraded,
        # never deadlocked). Without Redis the local lock still applies.
        flight_token = None
        flight_key = f"{key}:flight"
        if self._async_redis is not None:
            try:
                flight_token = secrets.token_hex(8)
                got = await self._async_redis.set(
                    flight_key, flight_token, nx=True, ex=self._FLIGHT_LEASE_SECONDS
                )
                if not got:
                    for _ in range(self._FLIGHT_POLLS):
                        await asyncio.sleep(self._FLIGHT_POLL_INTERVAL)
                        winner = await self.get(key, tier)
                        if winner is not None:
                            return winner
                    flight_token = None  # lease lost/expired - compute locally
            except Exception as e:
                logger.warning("Redis flight lock degraded (key=%s): %s", key, e)
                flight_token = None

        try:
            async with lock:
                # Double-check after acquiring lock
                cached = await self.get(key, tier)
                if cached is not None:
                    return cached

                # Compute value
                if asyncio.iscoroutinefunction(factory):
                    value = await factory()
                else:
                    value = factory()

                # Store in cache
                await self.set(key, value, tier)

                return value
        finally:
            if flight_token is not None and self._async_redis is not None:
                try:
                    # best-effort release: only delete our own lease
                    current = await self._async_redis.get(flight_key)
                    if current == flight_token:
                        await self._async_redis.delete(flight_key)
                except Exception as e:
                    logger.warning("Redis flight release failed (key=%s): %s", key, e)

    async def set(
        self,
        key: str,
        value: Any,
        tier: CacheTier = CacheTier.HOT,
        ttl_override: Optional[int] = None,
    ) -> bool:
        """Store value in cache with tier-based TTL."""
        await self.initialize()

        config = self._get_tier_config(tier)
        ttl = ttl_override if ttl_override is not None else config.ttl_seconds

        # Serialize value
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError) as e:
            logger.warning(f"Failed to serialize value for {key}: {e}")
            return False

        # Store in Redis
        if self._async_redis:
            try:
                await self._async_redis.setex(key, ttl, serialized)
                return True
            except Exception as e:
                logger.warning("Redis cache set degraded to memory (key=%s): %s", key, e)

        # Fallback to memory cache
        now = time.time()
        expiry = now + ttl
        stale_expiry = expiry + config.stale_while_revalidate
        self._memory_cache[key] = (value, expiry, stale_expiry)

        # LRU cleanup if needed
        if len(self._memory_cache) > config.max_entries:
            self._cleanup_memory_cache(config.max_entries // 10)

        return True

    async def delete(self, key: str) -> bool:
        """Delete a specific key from cache."""
        deleted = False

        if self._async_redis:
            try:
                deleted = bool(await self._async_redis.delete(key))
            except Exception as e:
                logger.debug(f"Redis delete failed for {key}: {e}")

        if key in self._memory_cache:
            del self._memory_cache[key]
            deleted = True

        return deleted

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching pattern.

        Use CacheKeyBuilder.pattern_for_invalidation() to build patterns.
        """
        count = 0

        if self._async_redis:
            try:
                cursor = 0
                while True:
                    cursor, keys = await self._async_redis.scan(
                        cursor=cursor, match=pattern, count=100
                    )
                    if keys:
                        count += await self._async_redis.delete(*keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis pattern invalidation failed for {pattern}: {e}")

        # Also clear from memory cache
        memory_pattern = pattern.rstrip("*")
        keys_to_delete = [k for k in self._memory_cache.keys() if k.startswith(memory_pattern)]
        for key in keys_to_delete:
            del self._memory_cache[key]
            count += 1

        return count

    async def invalidate_project(self, project_id: int) -> int:
        """Invalidate all cache entries for a project."""
        patterns = [
            CacheKeyBuilder.pattern_for_invalidation("analytics", "project", project_id),
            CacheKeyBuilder.pattern_for_invalidation("traceability", "project", project_id),
            CacheKeyBuilder.pattern_for_invalidation("tasks"),  # Tasks are cross-project
        ]

        total = 0
        for pattern in patterns:
            total += await self.invalidate_pattern(pattern)

        return total

    async def invalidate_sprint(self, sprint_id: int) -> int:
        """Invalidate all cache entries for a sprint."""
        pattern = CacheKeyBuilder.pattern_for_invalidation("analytics", "sprint", sprint_id)
        return await self.invalidate_pattern(pattern)

    def _cleanup_memory_cache(self, count: int = 100):
        """Remove oldest entries from memory cache."""
        if len(self._memory_cache) <= count:
            return

        # Sort by expiry time and remove oldest
        sorted_items = sorted(
            self._memory_cache.items(),
            key=lambda x: x[1][1],  # Sort by expiry
        )

        for key, _ in sorted_items[:count]:
            del self._memory_cache[key]

    async def close(self):
        """Close Redis connections."""
        if self._async_redis:
            await self._async_redis.close()
            self._async_redis = None


# =============================================================================
# Sync Cache for JIRA Services
# =============================================================================

# In-memory cache for sync JIRA operations
_sync_jira_cache: Dict[str, tuple[Any, float]] = {}
_sync_cache_lock = None  # Lazy-init threading lock


def _get_sync_cache_lock():
    """Get or create threading lock for sync cache."""
    global _sync_cache_lock
    if _sync_cache_lock is None:
        import threading

        _sync_cache_lock = threading.Lock()
    return _sync_cache_lock


def sync_cache_get(key: str) -> Optional[Any]:
    """
    Get value from sync cache.

    Returns None if not found or expired.
    Thread-safe for use in sync JIRA services.
    """
    # Extract cache type from key for metrics (e.g., "po_helper:jira:project:..." -> "jira")
    cache_type = key.split(":")[1] if ":" in key else "unknown"

    with _get_sync_cache_lock():
        if key in _sync_jira_cache:
            value, expiry = _sync_jira_cache[key]
            if time.time() < expiry:
                logger.debug(f"Sync cache hit: {key}")
                metrics.inc("cache_hits_total", labels={"type": cache_type})
                return value
            # Expired - remove it
            del _sync_jira_cache[key]

    metrics.inc("cache_misses_total", labels={"type": cache_type})
    return None


def sync_cache_set(key: str, value: Any, tier: CacheTier = CacheTier.COLD) -> None:
    """
    Store value in sync cache with tier-based TTL.

    Thread-safe for use in sync JIRA services.
    """
    config = TTL_POLICIES.get(tier, TTL_POLICIES[CacheTier.COLD])
    expiry = time.time() + config.ttl_seconds

    with _get_sync_cache_lock():
        _sync_jira_cache[key] = (value, expiry)

        # LRU cleanup if cache grows too large
        if len(_sync_jira_cache) > config.max_entries:
            _sync_cache_cleanup(config.max_entries // 10)


def _sync_cache_cleanup(count: int = 100) -> None:
    """Remove oldest entries from sync cache (must hold lock)."""
    if len(_sync_jira_cache) <= count:
        return

    # Sort by expiry and remove oldest
    sorted_items = sorted(_sync_jira_cache.items(), key=lambda x: x[1][1])

    for key, _ in sorted_items[:count]:
        del _sync_jira_cache[key]


def sync_cache_invalidate_jira() -> int:
    """Invalidate all JIRA cache entries."""
    count = 0
    with _get_sync_cache_lock():
        keys_to_delete = [k for k in _sync_jira_cache if k.startswith("po_helper:jira:")]
        for key in keys_to_delete:
            del _sync_jira_cache[key]
            count += 1
    logger.info(f"Invalidated {count} JIRA cache entries")
    return count


def sync_cached_jira(key_func: Callable[..., str], tier: CacheTier = CacheTier.COLD):
    """
    Sync caching decorator for JIRA service methods.

    Usage:
        @sync_cached_jira(
            key_func=lambda self, project_key: JiraCacheKeys.project(project_key),
            tier=CacheTier.COLD
        )
        def get_project(self, project_key: str) -> Dict[str, Any]:
            ...

    Args:
        key_func: Function to build cache key from method arguments
        tier: Cache tier for TTL (COLD=30min, WARM=5min, HOT=60s)

    Returns:
        Decorator function
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Build cache key
            try:
                cache_key = key_func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Failed to build JIRA cache key: {e}")
                return func(*args, **kwargs)

            # Check cache
            cached = sync_cache_get(cache_key)
            if cached is not None:
                return cached

            # Execute function
            result = func(*args, **kwargs)

            # Store in cache (only if successful - non-empty result)
            if result:
                sync_cache_set(cache_key, result, tier)

            return result

        return wrapper

    return decorator


# =============================================================================
# Caching Decorators for Endpoints
# =============================================================================


def cached_endpoint(
    key_builder: Callable[..., str],
    tier: CacheTier = CacheTier.HOT,
    cache_service: Optional[EnhancedCacheService] = None,
):
    """
    Decorator for caching FastAPI endpoint responses.

    Usage:
        @router.get("/projects/{project_id}/velocity")
        @cached_endpoint(
            key_builder=lambda project_id, sprints_count: AnalyticsCacheKeys.velocity(project_id, sprints_count),
            tier=CacheTier.WARM
        )
        async def get_project_velocity(project_id: int, sprints_count: int = 5, db = Depends(get_db)):
            ...
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from arguments
            try:
                cache_key = key_builder(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Failed to build cache key: {e}")
                return await func(*args, **kwargs)

            # Get cache service
            svc = cache_service or get_enhanced_cache_service()

            # Try cache first
            cached = await svc.get(cache_key, tier)
            if cached is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached

            # Execute function
            result = await func(*args, **kwargs)

            # Store in cache
            await svc.set(cache_key, result, tier)

            return result

        return wrapper

    return decorator


# =============================================================================
# Cache Warming Utilities
# =============================================================================


class CacheWarmer:
    """
    Utility for warming cache with commonly accessed data.

    Run on application startup or after bulk data changes.
    """

    def __init__(self, cache_service: EnhancedCacheService):
        self._cache = cache_service

    async def warm_project_analytics(
        self,
        project_id: int,
        db_session: Any,  # AsyncSession
    ):
        """Pre-compute and cache common project analytics."""

        tasks = [
            self._warm_velocity(project_id, db_session),
            self._warm_team_health(project_id, db_session),
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _warm_velocity(self, project_id: int, db_session: Any):
        """Warm velocity cache."""
        try:
            # Import here to avoid circular imports
            from app.api.api_v1.endpoints.analytics import get_project_velocity

            result = await get_project_velocity(project_id, 5, db_session)
            key = AnalyticsCacheKeys.velocity(project_id, 5)
            await self._cache.set(key, result, CacheTier.WARM)
        except Exception as e:
            logger.warning(f"Failed to warm velocity cache for project {project_id}: {e}")

    async def _warm_team_health(self, project_id: int, db_session: Any):
        """Warm team health cache."""
        try:
            from app.api.api_v1.endpoints.analytics import get_project_team_health

            result = await get_project_team_health(project_id, db_session)
            key = AnalyticsCacheKeys.team_health(project_id)
            await self._cache.set(key, result, CacheTier.HOT)
        except Exception as e:
            logger.warning(f"Failed to warm team health cache for project {project_id}: {e}")


# =============================================================================
# Global Cache Instance
# =============================================================================

# This will be initialized with Redis URL from settings
enhanced_cache_service: Optional[EnhancedCacheService] = None


def get_enhanced_cache_service() -> EnhancedCacheService:
    """Get or create the global enhanced cache service."""
    global enhanced_cache_service

    if enhanced_cache_service is None:
        from app.core.config import settings

        redis_url = getattr(settings, "REDIS_URL", None)
        enhanced_cache_service = EnhancedCacheService(redis_url)

    return enhanced_cache_service


# =============================================================================
# Cache Invalidation Hooks (for use in data modification endpoints)
# =============================================================================


class CacheInvalidator:
    """
    Helper for invalidating cache after data modifications.

    Usage in endpoints:
        @router.patch("/tasks/{task_id}")
        async def update_task(task_id: int, ...):
            # ... update logic ...
            await CacheInvalidator.on_task_update(task.project_id, task.sprint_id)
    """

    @staticmethod
    async def on_task_update(project_id: Optional[int], sprint_id: Optional[int]):
        """Invalidate caches affected by task changes."""
        cache = get_enhanced_cache_service()

        if project_id:
            await cache.invalidate_project(project_id)
        if sprint_id:
            await cache.invalidate_sprint(sprint_id)

    @staticmethod
    async def on_sprint_update(project_id: int, sprint_id: int):
        """Invalidate caches affected by sprint changes."""
        cache = get_enhanced_cache_service()
        await cache.invalidate_sprint(sprint_id)
        await cache.invalidate_project(project_id)

    @staticmethod
    async def on_artifact_link_change(project_id: Optional[int]):
        """Invalidate traceability caches."""
        cache = get_enhanced_cache_service()

        pattern = CacheKeyBuilder.pattern_for_invalidation("traceability")
        await cache.invalidate_pattern(pattern)

        if project_id:
            await cache.invalidate_project(project_id)

    @staticmethod
    async def on_jira_sync(project_id: int):
        """Invalidate all project-related caches after Jira sync."""
        cache = get_enhanced_cache_service()
        await cache.invalidate_project(project_id)

    @staticmethod
    async def on_quality_data_change(project_id: int):
        """Invalidate quality-related caches when defects or test data changes."""
        cache = get_enhanced_cache_service()

        # Invalidate all quality caches for this project
        pattern = CacheKeyBuilder.pattern_for_invalidation("quality", "project", project_id)
        await cache.invalidate_pattern(pattern)

        # Also invalidate general project caches that might include quality metrics
        await cache.invalidate_project(project_id)
