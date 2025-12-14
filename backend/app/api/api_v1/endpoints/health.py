from __future__ import annotations

from fastapi import APIRouter, Response, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.jira_service import jira_service
from app.services.confluence_service import confluence_service
from app.core.metrics import metrics
from app.core.database import get_db
from app.models.settings import IntegrationSetting

router = APIRouter()


@router.get("/")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "service": "po_helper"}


def _jira_status():
    mode = 'none'
    if jira_service.bearer_token:
        mode = 'PAT'
    elif jira_service.auth is not None:
        mode = 'Basic'
    return {
        'configured': jira_service.base_url is not None and (jira_service.bearer_token is not None or jira_service.auth is not None),
        'base_url': jira_service.base_url,
        'auth_mode': mode,
    }


def _confluence_status():
    s = confluence_service.status()
    return s


@router.get("/integrations")
async def integrations_status(db: AsyncSession = Depends(get_db)):
    # Use caching to avoid repeated database queries
    from app.services.cache_service import cache_service
    cache_key = cache_service._make_key("integrations_status")
    cached_result = cache_service.get(cache_key)
    if cached_result:
        return cached_result

    data = {
        'jira': _jira_status(),
        'confluence': _confluence_status(),
        'github': { 'configured': False },
        'gitlab': { 'configured': False },
        'testrail': { 'configured': False },
    }

    try:
        # Add timeout protection for database query
        import asyncio
        result = await asyncio.wait_for(
            db.execute(select(IntegrationSetting)),
            timeout=5.0  # 5 second timeout
        )
        for row in result.scalars().all():
            if row.kind == 'jira':
                data['jira']['has_token'] = bool(row.api_token)
                # Don't overwrite configured status from in-memory service
                if bool(row.base_url) and bool(row.api_token):
                    data['jira']['configured'] = True
            elif row.kind == 'confluence':
                data['confluence']['has_token'] = bool(row.api_token)
                # Don't overwrite configured status from in-memory service
                if bool(row.base_url) and bool(row.api_token):
                    data['confluence']['configured'] = True
            elif row.kind == 'github':
                data['github']['has_token'] = bool(row.api_token)
                data['github']['configured'] = bool(row.api_token)
            elif row.kind == 'gitlab':
                data['gitlab']['has_token'] = bool(row.api_token)
                data['gitlab']['configured'] = bool(row.base_url) and bool(row.api_token)
            elif row.kind == 'testrail':
                data['testrail']['has_token'] = bool(row.api_token)
                data['testrail']['configured'] = bool(row.base_url) and bool(row.api_token)
    except asyncio.TimeoutError:
        # Return basic status without database info on timeout
        pass
    except Exception:
        pass

    # Cache the result for 30 seconds
    cache_service.set(cache_key, data, ttl=30)
    return data


@router.get("/integrations/{name}/status")
async def integration_status(name: str, db: AsyncSession = Depends(get_db)):
    nm = name.lower()
    if nm == 'jira':
        payload = _jira_status()
    elif nm == 'confluence':
        payload = _confluence_status()
    elif nm in ('github','gitlab','testrail'):
        payload = { 'configured': False }
    else:
        return {'configured': False, 'detail': 'unknown integration'}
    try:
        result = await db.execute(select(IntegrationSetting).where(IntegrationSetting.kind == nm))
        row = result.scalar_one_or_none()
        if row:
            payload['has_token'] = bool(row.api_token)
            if nm in ('github','gitlab','testrail'):
                payload['configured'] = bool(row.base_url) or nm=='github'
    except Exception:
        pass
    return payload


@router.get("/metrics")
async def metrics_export() -> Response:
    data = metrics.export_prometheus()
    return Response(content=data, media_type="text/plain; version=0.0.4")
