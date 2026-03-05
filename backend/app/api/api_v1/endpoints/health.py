from __future__ import annotations

import asyncio
import logging
from time import perf_counter

from fastapi import APIRouter, Response, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.jira_service import jira_service
from app.services.confluence_service import confluence_service
from app.core.metrics import metrics
from app.core.database import get_db
from app.models.settings import IntegrationSetting

router = APIRouter()
logger = logging.getLogger(__name__)

HEALTH_INTEGRATIONS_SLOW_THRESHOLD_SECONDS = 2.0


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
