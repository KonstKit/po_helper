"""HTTP endpoints for product usage analytics.

Track endpoints accept events from authenticated clients and persist them.
Metrics endpoints return aggregated dashboards (admin-only).
"""

import hashlib
import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import _resolve_current_user, get_current_user_strict
from app.core.config import settings
from app.core.request_context import get_token_scopes, get_token_tenant_id
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import decode_token
from app.models.rbac import Permissions
from app.models.user import User

logger = logging.getLogger(__name__)
from app.schemas.analytics_event import (
    AnalyticsEventBatchIn,
    AnalyticsEventIn,
    FeatureAdoptionMetricsOut,
    OnboardingMetricsOut,
    TimeToValueMetricsOut,
    TrackResponse,
    UsageSummaryOut,
)
from app.services import analytics_service

router = APIRouter()


def _require_global_admin_strict():
    """Admin-only guard that *also* rejects tenant-scoped tokens.

    Stopgap until usage analytics is tenant-aware (no `tenant_id` column
    on `analytics_event`, no per-tenant filtering in aggregations). Until
    that work lands, a tenant-scoped admin token would otherwise be able
    to read or delete cross-tenant aggregates here, because the rest of
    the analytics pipeline is global. Fail closed.

    Track endpoints intentionally do NOT use this guard: they only write
    a row owned by the calling user; tenant-scoped users can still emit
    their own telemetry. Only reads/deletes of the aggregated, global
    dataset are gated to global operators.
    """

    async def _check(
        current_user: User = Depends(get_current_user_strict),
    ) -> User:
        if get_token_tenant_id() is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Usage analytics admin metrics are global-only "
                    "until tenant-scoped analytics is implemented."
                ),
            )
        token_scopes = get_token_scopes()
        if (
            token_scopes is not None
            and Permissions.ADMIN not in token_scopes
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {Permissions.ADMIN}",
            )
        if token_scopes is None and not current_user.has_permission(
            Permissions.ADMIN
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied. Required: {Permissions.ADMIN}",
            )
        return current_user

    return _check


def _user_or_ip_key(request: Request) -> str:
    """Rate-limit by authenticated user when the JWT is valid, IP otherwise.

    The shared `limiter` keys by `request.client.host` by default, which
    means every authenticated user behind the same NAT/proxy egress IP
    shares one quota — and `/track*` would exhaust per-team. We key by the
    JWT `sub` claim so each authenticated user gets their own bucket.

    We MUST verify the token before deriving the bucket key. If we hashed
    the raw bearer string, an unauthenticated client could vary a bogus
    token on every request and trivially bypass the IP bucket. Decoding
    here verifies signature + expiry exactly like `get_current_user` does.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer ") and len(auth) > 7:
        token = auth[7:]
        try:
            payload = decode_token(token)
        except Exception:  # JWT invalid/expired — fall through to IP key.
            return get_remote_address(request)
        sub = payload.get("sub")
        if sub:
            digest = hashlib.sha256(str(sub).encode("utf-8")).hexdigest()[:16]
            return f"analytics-user:{digest}"
    return get_remote_address(request)


async def _resolve_track_caller(
    db: AsyncSession = Depends(get_db),
    authorization: Optional[str] = Header(default=None, convert_underscores=False),
) -> Optional[User]:
    """Resolve the caller for /track endpoints.

    Requires a valid JWT (missing/invalid → 401), but tolerates the
    "JWT decoded but no provisioned User row" case by returning None
    instead of 404 — that lets the service layer fall back to anonymous,
    session-keyed recording for users in lazy-provisioning / external-
    auth flows that can produce a valid token before a User row exists.
    """
    try:
        return await _resolve_current_user(
            db,
            authorization=authorization,
            allow_debug_demo_fallback=False,
        )
    except HTTPException as exc:
        # 404 = JWT was valid (signature + claims) but no matching User.
        # Accept anonymously. Any other status (notably 401) is a real
        # auth failure and must propagate.
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return None
        raise


def _enforce_batch_size(events_in: AnalyticsEventBatchIn) -> None:
    max_size = settings.ANALYTICS_BATCH_MAX_SIZE
    if len(events_in.events) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch exceeds ANALYTICS_BATCH_MAX_SIZE={max_size}",
        )


@router.post("/track", response_model=TrackResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("100/minute", key_func=_user_or_ip_key)
async def track_event(
    request: Request,
    event: AnalyticsEventIn,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(_resolve_track_caller),
) -> TrackResponse:
    """Persist a single analytics event for the authenticated caller.

    A valid JWT without a provisioned User row records the event with
    user_id=None (session-keyed), so first-session telemetry under lazy
    provisioning / external auth is preserved instead of 404'ing.
    """
    await analytics_service.record_event(
        db, event, user_id=current_user.id if current_user else None
    )
    return TrackResponse(accepted=1, received_at=int(time.time() * 1000))


@router.post(
    "/track/batch",
    response_model=TrackResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("60/minute", key_func=_user_or_ip_key)
async def track_events_batch(
    request: Request,
    payload: AnalyticsEventBatchIn,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(_resolve_track_caller),
) -> TrackResponse:
    """Persist a batch of analytics events for the authenticated caller."""
    _enforce_batch_size(payload)
    accepted = await analytics_service.record_events_batch(
        db, payload.events, user_id=current_user.id if current_user else None
    )
    return TrackResponse(accepted=accepted, received_at=int(time.time() * 1000))


@router.get("/metrics/onboarding", response_model=OnboardingMetricsOut)
async def get_onboarding_metrics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_global_admin_strict()),
) -> OnboardingMetricsOut:
    return await analytics_service.compute_onboarding_metrics(db)


@router.get("/metrics/time-to-value", response_model=TimeToValueMetricsOut)
async def get_time_to_value_metrics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_global_admin_strict()),
) -> TimeToValueMetricsOut:
    return await analytics_service.compute_time_to_value(db)


@router.get("/metrics/feature-adoption", response_model=FeatureAdoptionMetricsOut)
async def get_feature_adoption_metrics(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_global_admin_strict()),
) -> FeatureAdoptionMetricsOut:
    return await analytics_service.compute_feature_adoption(db)


@router.get("/metrics/summary", response_model=UsageSummaryOut)
async def get_usage_metrics_summary(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_global_admin_strict()),
) -> UsageSummaryOut:
    return await analytics_service.compute_summary(db)


@router.delete("/events", status_code=status.HTTP_204_NO_CONTENT)
async def clear_analytics_data(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_global_admin_strict()),
) -> None:
    """Delete all analytics events. Admin-only."""
    await analytics_service.clear_events(db)
