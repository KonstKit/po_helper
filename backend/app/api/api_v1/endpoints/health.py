from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Response, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select, text

from app.services.jira_service import jira_service
from app.services.confluence_service import confluence_service
from app.core.metrics import metrics
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.models.settings import IntegrationSetting
from app.models.traceability import SyncTask as SyncTaskModel

router = APIRouter()
logger = logging.getLogger(__name__)

HEALTH_INTEGRATIONS_SLOW_THRESHOLD_SECONDS = 2.0
READINESS_TIMEOUT_SECONDS = 3.0


def _record_integrations_guardrail(
    *,
    duration: float,
    status: str,
    cache_hit: bool = False,
) -> None:
    is_degraded = status in {"db_timeout", "db_error", "error"}

    try:
        metrics.observe(
            "api_endpoint_duration_seconds",
            duration,
            labels={
                "endpoint": "health_integrations",
                "status": status,
                "cache_hit": str(cache_hit).lower(),
            },
        )
        if is_degraded:
            metrics.inc(
                "api_endpoint_degraded_total",
                labels={"endpoint": "health_integrations", "status": status},
            )
        if duration > HEALTH_INTEGRATIONS_SLOW_THRESHOLD_SECONDS:
            metrics.inc(
                "api_endpoint_slow_total",
                labels={"endpoint": "health_integrations"},
            )
    except Exception:
        pass

    if is_degraded:
        logger.warning(
            "health.integrations.degraded status=%s cache_hit=%s duration=%.3f",
            status,
            cache_hit,
            duration,
        )
    elif duration > HEALTH_INTEGRATIONS_SLOW_THRESHOLD_SECONDS:
        logger.warning(
            "health.integrations.slow duration=%.3f threshold=%.3f cache_hit=%s",
            duration,
            HEALTH_INTEGRATIONS_SLOW_THRESHOLD_SECONDS,
            cache_hit,
        )


@router.get("/")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "po_helper"}


async def _check_database_readiness() -> tuple[bool, str]:
    try:
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=READINESS_TIMEOUT_SECONDS)
        return True, "ok"
    except asyncio.TimeoutError:
        return False, "timeout"
    except Exception:
        logger.warning("health.ready.database_failed", exc_info=True)
        return False, "error"


def _is_redis_required_for_runtime() -> bool:
    """
    Redis is a hard readiness dependency only when Celery runtime is enabled.
    In API-only mode, Redis-backed features degrade gracefully.
    """
    return bool(settings.CELERY_ENABLED)


def _ping_redis_blocking(redis_url: str) -> None:
    import redis

    client = redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=READINESS_TIMEOUT_SECONDS,
        socket_timeout=READINESS_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


async def _check_redis_readiness() -> tuple[bool, str]:
    if not settings.REDIS_URL:
        return False, "not_configured"

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_ping_redis_blocking, settings.REDIS_URL),
            timeout=READINESS_TIMEOUT_SECONDS,
        )
        return True, "ok"
    except asyncio.TimeoutError:
        return False, "timeout"
    except ImportError:
        return False, "client_unavailable"
    except Exception:
        logger.warning("health.ready.redis_failed", exc_info=True)
        return False, "error"


def _get_celery_queue_name() -> str:
    try:
        from app.core.celery_app import celery_app

        queue_name = getattr(celery_app.conf, "task_default_queue", None) or "celery"
        return str(queue_name)
    except Exception:
        return "celery"


async def _check_celery_queue_readiness() -> tuple[bool, str, dict[str, Any]]:
    queue_name = _get_celery_queue_name()
    threshold = int(getattr(settings, "ALERT_QUEUE_BACKLOG_THRESHOLD", 100) or 100)
    base_payload: dict[str, Any] = {
        "required": bool(settings.CELERY_ENABLED),
        "queue_name": queue_name,
        "backlog": 0,
        "backlog_threshold": threshold,
    }

    if not settings.CELERY_ENABLED:
        return True, "disabled", base_payload

    broker_url = settings.CELERY_BROKER_URL or settings.REDIS_URL
    if not broker_url:
        return False, "not_configured", base_payload

    broker_scheme = (urlparse(broker_url).scheme or "").lower()
    if broker_scheme not in {"redis", "rediss"}:
        base_payload["status"] = "probe_not_supported"
        return True, "probe_not_supported", base_payload

    try:
        import redis

        def _probe_backlog() -> int:
            client = redis.from_url(
                broker_url,
                decode_responses=True,
                socket_connect_timeout=READINESS_TIMEOUT_SECONDS,
                socket_timeout=READINESS_TIMEOUT_SECONDS,
            )
            try:
                client.ping()
                return int(client.llen(queue_name))
            finally:
                client.close()

        backlog = await asyncio.wait_for(
            asyncio.to_thread(_probe_backlog),
            timeout=READINESS_TIMEOUT_SECONDS,
        )
        base_payload["backlog"] = backlog
        try:
            metrics.set_gauge("celery_queue_backlog", backlog, labels={"queue": queue_name})
            metrics.set_gauge(
                "celery_queue_backlog_threshold",
                threshold,
                labels={"queue": queue_name},
            )
        except Exception:
            pass
        if backlog >= threshold:
            base_payload["status"] = "backlog_high"
            return False, "backlog_high", base_payload
        base_payload["status"] = "ok"
        return True, "ok", base_payload
    except asyncio.TimeoutError:
        base_payload["status"] = "probe_timeout"
        return True, "probe_timeout", base_payload
    except ImportError:
        base_payload["status"] = "client_unavailable"
        return True, "client_unavailable", base_payload
    except Exception:
        logger.warning("health.ready.queue_failed", exc_info=True)
        base_payload["status"] = "probe_error"
        return True, "probe_error", base_payload


async def _recent_sync_failure_alerts(db: AsyncSession) -> dict[str, Any]:
    window_seconds = int(getattr(settings, "ALERT_SYNC_FAILURE_WINDOW_SECONDS", 86400) or 86400)
    threshold = int(getattr(settings, "ALERT_SYNC_FAILURE_THRESHOLD", 5) or 5)
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    stmt = (
        select(SyncTaskModel.task_type, func.count(SyncTaskModel.id))
        .where(SyncTaskModel.status == "failed")
        .where(
            or_(
                SyncTaskModel.finished_at >= cutoff,
                SyncTaskModel.created_at >= cutoff,
            )
        )
        .group_by(SyncTaskModel.task_type)
        .order_by(SyncTaskModel.task_type)
    )
    result = await db.execute(stmt)
    rows = result.all()
    by_type = {task_type: int(count) for task_type, count in rows}
    total_failures = sum(by_type.values())
    triggered = total_failures >= threshold
    return {
        "triggered": triggered,
        "window_seconds": window_seconds,
        "threshold": threshold,
        "total_failures": total_failures,
        "by_type": by_type,
    }


def _recent_api_error_alert() -> dict[str, Any]:
    window_seconds = int(getattr(settings, "ALERT_API_ERROR_WINDOW_SECONDS", 300) or 300)
    threshold = int(getattr(settings, "ALERT_API_ERROR_THRESHOLD", 20) or 20)
    error_count = int(metrics.recent_counter_sum("http_request_errors", window_seconds))
    request_count = int(metrics.recent_counter_sum("http_requests", window_seconds))
    triggered = error_count >= threshold
    return {
        "triggered": triggered,
        "window_seconds": window_seconds,
        "threshold": threshold,
        "error_count": error_count,
        "request_count": request_count,
    }


@router.get("/ready")
async def readiness_check() -> JSONResponse:
    db_ok, db_status = await _check_database_readiness()
    redis_ok, redis_status = await _check_redis_readiness()
    redis_required = _is_redis_required_for_runtime()
    redis_ready = redis_ok if redis_required else True
    queue_ok, queue_status, queue_details = await _check_celery_queue_readiness()
    is_ready = db_ok and redis_ready and queue_ok

    payload = {
        "status": "ready" if is_ready else "degraded",
        "service": "po_helper",
        "dependencies": {
            "database": {"ok": db_ok, "status": db_status},
            "redis": {"ok": redis_ok, "status": redis_status, "required": redis_required},
            "queue": {"ok": queue_ok, **queue_details, "status": queue_status},
        },
    }
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)


def _jira_status():
    return jira_service.status()


def _confluence_status():
    s = confluence_service.status()
    return s


@router.get("/integrations")
async def integrations_status(db: AsyncSession = Depends(get_db)):
    start = perf_counter()

    # Use caching to avoid repeated database queries
    from app.services.cache_service import cache_service

    cache_key = cache_service._make_key("integrations_status")
    cached_result = cache_service.get(cache_key)
    if cached_result:
        _record_integrations_guardrail(
            duration=perf_counter() - start,
            status="ok",
            cache_hit=True,
        )
        return cached_result

    data = {
        "jira": _jira_status(),
        "confluence": _confluence_status(),
        "github": {"configured": False},
        "gitlab": {"configured": False},
        "bitbucket": {"configured": False},
        "testrail": {"configured": False},
    }

    status = "ok"
    try:
        # Add timeout protection for database query
        result = await asyncio.wait_for(
            db.execute(select(IntegrationSetting)),
            timeout=5.0,  # 5 second timeout
        )
        for row in result.scalars().all():
            if row.kind == "jira":
                data["jira"]["has_token"] = bool(row.api_token)
                # Don't overwrite configured status from in-memory service
                if bool(row.base_url) and bool(row.api_token):
                    data["jira"]["configured"] = True
            elif row.kind == "confluence":
                data["confluence"]["has_token"] = bool(row.api_token)
                # Don't overwrite configured status from in-memory service
                if bool(row.base_url) and bool(row.api_token):
                    data["confluence"]["configured"] = True
            elif row.kind == "github":
                data["github"]["has_token"] = bool(row.api_token)
                data["github"]["configured"] = bool(row.api_token)
            elif row.kind == "gitlab":
                data["gitlab"]["has_token"] = bool(row.api_token)
                data["gitlab"]["configured"] = bool(row.base_url) and bool(row.api_token)
            elif row.kind == "bitbucket":
                data["bitbucket"]["has_token"] = bool(row.api_token)
                data["bitbucket"]["configured"] = bool(row.base_url) and bool(row.api_token)
            elif row.kind == "testrail":
                data["testrail"]["has_token"] = bool(row.api_token)
                data["testrail"]["configured"] = bool(row.base_url) and bool(row.api_token)
    except asyncio.TimeoutError:
        # Return basic status without database info on timeout
        status = "db_timeout"
        pass
    except Exception:
        status = "db_error"
        pass

    # Cache the result for 30 seconds
    cache_service.set(cache_key, data, ttl=30)
    _record_integrations_guardrail(
        duration=perf_counter() - start,
        status=status,
    )
    return data


@router.get("/integrations/{name}/status")
async def integration_status(name: str, db: AsyncSession = Depends(get_db)):
    nm = name.lower()
    if nm == "jira":
        payload = _jira_status()
    elif nm == "confluence":
        payload = _confluence_status()
    elif nm in ("github", "gitlab", "bitbucket", "testrail"):
        payload = {"configured": False}
    else:
        return {"configured": False, "detail": "unknown integration"}
    try:
        result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == nm))
        row = result.scalar_one_or_none()
        if row:
            payload["has_token"] = bool(row.api_token)
            if nm in ("github", "gitlab", "bitbucket", "testrail"):
                payload["configured"] = bool(row.base_url) or nm == "github"
    except Exception:
        pass
    return payload


@router.get("/metrics")
async def metrics_export() -> Response:
    data = metrics.export_prometheus()
    return Response(content=data, media_type="text/plain; version=0.0.4")


@router.get("/alerts")
async def alerts(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    alerts_payload: list[dict[str, Any]] = []

    api_errors = _recent_api_error_alert()
    if api_errors["triggered"]:
        alerts_payload.append(
            {
                "name": "sustained_api_errors",
                "severity": "warning",
                "triggered": True,
                "details": api_errors,
            }
        )

    queue_ok, queue_status, queue_details = await _check_celery_queue_readiness()
    if settings.CELERY_ENABLED and not queue_ok and queue_status == "backlog_high":
        alerts_payload.append(
            {
                "name": "queue_backlog_threshold",
                "severity": "warning",
                "triggered": True,
                "details": queue_details,
            }
        )

    sync_failures = await _recent_sync_failure_alerts(db)
    if sync_failures["triggered"]:
        alerts_payload.append(
            {
                "name": "repeated_sync_failures",
                "severity": "warning",
                "triggered": True,
                "details": sync_failures,
            }
        )

    return JSONResponse(
        content={
            "status": "degraded" if alerts_payload else "ok",
            "service": "po_helper",
            "alerts": alerts_payload,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    )
