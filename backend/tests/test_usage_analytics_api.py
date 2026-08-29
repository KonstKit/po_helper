"""Tests for /api/v1/usage-analytics endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.analytics import AnalyticsEvent
from app.models.user import User


API_PREFIX = "/api/v1/usage-analytics"


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


@pytest_asyncio.fixture
async def seeded_user(db_session):
    """Insert a real `users` row with id=1 (matches `_DummyUser.id`)
    and `created_at` set 1 hour in the past, so JOIN-based aggregations
    (TTV) can compute deltas against a known baseline.
    """
    user = User(
        id=1,
        email="test@example.com",
        username="test",
        full_name="Test User",
        is_active=True,
        is_superuser=True,
        created_at=datetime.now(tz=timezone.utc) - timedelta(hours=1),
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.mark.asyncio
async def test_track_single_event_persists(client, db_session):
    body = {
        "eventName": "page_view",
        "eventData": {"page": "projects"},
        "timestamp": _now_ms(),
        "sessionId": "session-A",
    }
    response = await client.post(f"{API_PREFIX}/track", json=body)
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["accepted"] == 1
    assert "receivedAt" in payload

    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert len(rows) == 1
    saved = rows[0]
    assert saved.event_name == "page_view"
    assert saved.session_id == "session-A"
    assert saved.user_id == 1  # _DummyUser.id from conftest
    assert saved.event_data == {"page": "projects"}


@pytest.mark.asyncio
async def test_track_batch_persists_all(client, db_session):
    events = [
        {
            "eventName": "page_view",
            "eventData": {"page": "tasks"},
            "timestamp": _now_ms(),
            "sessionId": "session-B",
        },
        {
            "eventName": "onboarding_started",
            "timestamp": _now_ms(),
            "sessionId": "session-B",
        },
    ]
    response = await client.post(f"{API_PREFIX}/track/batch", json={"events": events})
    assert response.status_code == 201, response.text
    assert response.json()["accepted"] == 2

    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert len(rows) == 2
    assert {r.event_name for r in rows} == {"page_view", "onboarding_started"}


@pytest.mark.asyncio
async def test_track_batch_rejects_oversize(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "ANALYTICS_BATCH_MAX_SIZE", 2)
    payload = {
        "events": [
            {
                "eventName": "page_view",
                "timestamp": _now_ms(),
                "sessionId": "s",
            }
            for _ in range(3)
        ]
    }
    response = await client.post(f"{API_PREFIX}/track/batch", json=payload)
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_metrics_onboarding_aggregates_correctly(client, db_session):
    base_ts = _now_ms()
    events = [
        {
            "eventName": "onboarding_started",
            "timestamp": base_ts,
            "sessionId": "s1",
        },
        {
            "eventName": "onboarding_step_completed",
            "eventData": {"step": 1},
            "timestamp": base_ts + 10_000,
            "sessionId": "s1",
        },
        {
            "eventName": "onboarding_step_completed",
            "eventData": {"step": 2},
            "timestamp": base_ts + 20_000,
            "sessionId": "s1",
        },
        {
            "eventName": "onboarding_completed",
            "timestamp": base_ts + 30_000,
            "sessionId": "s1",
        },
        {
            "eventName": "onboarding_started",
            "timestamp": base_ts,
            "sessionId": "s2",
        },
        {
            "eventName": "onboarding_skipped",
            "timestamp": base_ts + 5_000,
            "sessionId": "s2",
        },
    ]
    for ev in events:
        r = await client.post(f"{API_PREFIX}/track", json=ev)
        assert r.status_code == 201

    response = await client.get(f"{API_PREFIX}/metrics/onboarding")
    assert response.status_code == 200, response.text
    payload = response.json()
    # _attempt_identity keys by session_id (namespaced by user) so the two
    # sessions are counted as two separate onboarding attempts even though
    # they share user_id=1 (the conftest DummyUser).
    #   s1: started → step1 → step2 → completed (30s)
    #   s2: started → skipped (5s)
    assert payload["startedCount"] == 2
    assert payload["completedCount"] == 1
    assert payload["skippedCount"] == 1
    assert payload["completionRate"] == pytest.approx(0.5)
    assert payload["stepCompletion"] == {"1": 1, "2": 1}
    # Attrition: step1→step2 = 0, step2→completed = 0. Perfect-funnel for
    # the only attempt that reached the step phase, so no drop-off.
    assert payload["dropOffStep"] is None
    assert payload["avgTimeToCompleteSec"] == pytest.approx(30.0, abs=0.5)


@pytest.mark.asyncio
async def test_metrics_feature_adoption(client):
    base_ts = _now_ms()
    for page in ("projects", "tasks", "analytics"):
        r = await client.post(
            f"{API_PREFIX}/track",
            json={
                "eventName": "page_view",
                "eventData": {"page": page},
                "timestamp": base_ts,
                "sessionId": f"session-{page}",
            },
        )
        assert r.status_code == 201

    response = await client.get(f"{API_PREFIX}/metrics/feature-adoption")
    assert response.status_code == 200
    payload = response.json()
    assert payload["features"]["projects"] >= 1
    assert payload["features"]["tasks"] >= 1
    assert payload["features"]["analytics"] >= 1
    assert payload["adoptionRate"] > 0


@pytest.mark.asyncio
async def test_metrics_summary_returns_valid_shape(client):
    response = await client.get(f"{API_PREFIX}/metrics/summary")
    assert response.status_code == 200
    payload = response.json()
    for key in (
        "onboardingCompletionRate",
        "featureAdoptionRate",
        "activeUsersCount",
    ):
        assert key in payload


@pytest.mark.asyncio
async def test_delete_events_clears_table(client, db_session):
    await client.post(
        f"{API_PREFIX}/track",
        json={
            "eventName": "page_view",
            "timestamp": _now_ms(),
            "sessionId": "s",
        },
    )
    rows_before = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert len(rows_before) >= 1

    response = await client.delete(f"{API_PREFIX}/events")
    assert response.status_code == 204

    await db_session.commit()  # release any pending tx state
    rows_after = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert rows_after == []


@pytest.mark.asyncio
async def test_track_rejects_blank_event_name(client):
    """Pydantic validator must reject whitespace-only event names."""
    body = {
        "eventName": "   ",
        "timestamp": _now_ms(),
        "sessionId": "s",
    }
    response = await client.post(f"{API_PREFIX}/track", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_track_rejects_oversized_event_data(client, monkeypatch):
    """Reject oversized JSON payloads at the schema boundary."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "ANALYTICS_EVENT_DATA_MAX_BYTES", 32)
    body = {
        "eventName": "page_view",
        "eventData": {"page": "x" * 64},  # well over 32 bytes serialised
        "timestamp": _now_ms(),
        "sessionId": "s",
    }
    response = await client.post(f"{API_PREFIX}/track", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_track_rejects_far_future_timestamp(client):
    """Reject timestamps past the configured skew tolerance."""
    far_future = _now_ms() + 7 * 24 * 3600 * 1000  # 7 days ahead
    body = {
        "eventName": "page_view",
        "timestamp": far_future,
        "sessionId": "s",
    }
    response = await client.post(f"{API_PREFIX}/track", json=body)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_track_strips_event_name_whitespace(client, db_session):
    body = {
        "eventName": "  page_view  ",
        "timestamp": _now_ms(),
        "sessionId": "s",
    }
    response = await client.post(f"{API_PREFIX}/track", json=body)
    assert response.status_code == 201

    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert rows[0].event_name == "page_view"


@pytest.mark.asyncio
async def test_ttv_uses_users_created_at_as_baseline(client, db_session, seeded_user):
    """TTV baseline must come from `users.created_at`, not the client
    `accountCreatedAt` milestone. Send only `firstSyncAt` to prove the
    server does not require the client baseline event."""
    base_ts = _now_ms()
    response = await client.post(
        f"{API_PREFIX}/track",
        json={
            "eventName": "time_to_value_milestone",
            "eventData": {"milestone": "firstSyncAt"},
            "timestamp": base_ts,
            "sessionId": "s",
        },
    )
    assert response.status_code == 201

    response = await client.get(f"{API_PREFIX}/metrics/time-to-value")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sampleSize"] == 1
    # Baseline = seeded_user.created_at (1 hour ago); milestone = now.
    # Expect ~3600s ± a few seconds.
    delta = payload["avgToFirstSyncSec"]
    assert delta is not None
    assert 3500 < delta < 3700, f"unexpected delta {delta}"


@pytest.mark.asyncio
async def test_ttv_excludes_anonymous_events(client, db_session):
    """Without seeded_user, FK fallback drops user_id, so events become
    anonymous and TTV must report sample_size=0."""
    response = await client.post(
        f"{API_PREFIX}/track",
        json={
            "eventName": "time_to_value_milestone",
            "eventData": {"milestone": "firstSyncAt"},
            "timestamp": _now_ms(),
            "sessionId": "s",
        },
    )
    assert response.status_code == 201

    # Force the only event to be anonymous (FK off in SQLite tests means our
    # IntegrityError fallback never fires; mutate the row directly).
    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    for row in rows:
        row.user_id = None
    await db_session.commit()

    response = await client.get(f"{API_PREFIX}/metrics/time-to-value")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sampleSize"] == 0
    assert payload["avgToFirstSyncSec"] is None


@pytest.mark.asyncio
async def test_least_used_includes_zero_count_features(client):
    """Features with 0 visits must appear in least_used (the signal PMs
    are looking for). Tie-break is deterministic by FEATURE_PAGES order."""
    base_ts = _now_ms()
    # Visit only one feature, leaving the rest at zero.
    r = await client.post(
        f"{API_PREFIX}/track",
        json={
            "eventName": "page_view",
            "eventData": {"page": "projects"},
            "timestamp": base_ts,
            "sessionId": "s",
        },
    )
    assert r.status_code == 201

    response = await client.get(f"{API_PREFIX}/metrics/feature-adoption")
    assert response.status_code == 200
    payload = response.json()
    least_used = payload["leastUsed"]
    # Zero-count features must populate least_used; "projects" must not be
    # there since it has a visit.
    assert "projects" not in least_used
    assert len(least_used) == 3
    # All names in least_used should have count 0 in the features map.
    for name in least_used:
        assert payload["features"][name] == 0


@pytest.mark.asyncio
async def test_cleanup_removes_only_stale_events(db_session):
    """cleanup_analytics_events removes rows past retention, leaves recent
    ones in place. Tests the async function directly (the celery wrapper
    just calls it through run_async)."""
    from app.tasks.maintenance_tasks import cleanup_analytics_events

    now = datetime.now(tz=timezone.utc)
    fresh = AnalyticsEvent(
        event_name="page_view",
        event_data={"page": "projects"},
        occurred_at=now - timedelta(hours=1),
        session_id="fresh",
    )
    stale = AnalyticsEvent(
        event_name="page_view",
        event_data={"page": "tasks"},
        occurred_at=now - timedelta(days=10),
        session_id="stale",
    )
    db_session.add_all([fresh, stale])
    await db_session.commit()

    deleted = await cleanup_analytics_events(retention_days=1)
    assert deleted == 1

    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    remaining_sessions = {r.session_id for r in rows}
    assert remaining_sessions == {"fresh"}


@pytest.mark.asyncio
async def test_cleanup_no_op_when_retention_disabled(db_session):
    from app.tasks.maintenance_tasks import cleanup_analytics_events

    now = datetime.now(tz=timezone.utc)
    db_session.add(
        AnalyticsEvent(
            event_name="page_view",
            occurred_at=now - timedelta(days=365),
            session_id="ancient",
        )
    )
    await db_session.commit()

    assert await cleanup_analytics_events(retention_days=0) == 0
    rows = (await db_session.execute(select(AnalyticsEvent))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_metrics_reject_tenant_scoped_admin(client, monkeypatch):
    """Tenant-scoped admin tokens must be rejected on /metrics/* and
    DELETE /events until usage analytics is tenant-aware (no tenant_id
    column on analytics_event yet). Closes the cross-tenant read/delete
    exposure via fail-closed admin guard."""
    from app.api.api_v1.endpoints import usage_analytics as ep

    # Simulate a tenant-scoped token: get_token_tenant_id() is a
    # ContextVar getter, so monkeypatching the imported reference inside
    # the endpoint module is the cleanest way to fake "this request
    # arrived with tenant scope".
    monkeypatch.setattr(ep, "get_token_tenant_id", lambda: "tenant-A")

    for path in (
        "/metrics/onboarding",
        "/metrics/time-to-value",
        "/metrics/feature-adoption",
        "/metrics/summary",
    ):
        r = await client.get(f"{API_PREFIX}{path}")
        assert r.status_code == 403, f"{path} should reject tenant token, got {r.status_code}"
        assert "global-only" in r.json().get("detail", "")

    r = await client.delete(f"{API_PREFIX}/events")
    assert r.status_code == 403
    assert "global-only" in r.json().get("detail", "")


@pytest.mark.asyncio
async def test_metrics_allow_global_admin(client, monkeypatch):
    """Sanity check: with no tenant scope on the token, global admin
    still reaches metrics + delete. Guards against an over-restrictive
    refactor of _require_global_admin_strict."""
    from app.api.api_v1.endpoints import usage_analytics as ep

    monkeypatch.setattr(ep, "get_token_tenant_id", lambda: None)

    r = await client.get(f"{API_PREFIX}/metrics/summary")
    assert r.status_code == 200
    r = await client.delete(f"{API_PREFIX}/events")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_strict_endpoints_reject_no_token():
    """With no Authorization header (and DEBUG fallback effectively absent),
    `/track*`, `/metrics/*`, `DELETE /events` must all 401. This is the
    exact regression the get_current_user_strict swap defends against —
    any future revert that lets the DEBUG demo fallback bleed through
    would otherwise go unnoticed because conftest.py globally injects a
    dummy user. Here we drop the overrides and run an isolated client
    that talks to the real dependency."""
    from httpx import AsyncClient

    from app.api.deps import (
        get_current_user,
        get_current_user_strict,
        require_integration_access,
    )
    from app.core.config import settings as app_settings
    from app.main import app

    saved = {
        get_current_user: app.dependency_overrides.pop(get_current_user, None),
        get_current_user_strict: app.dependency_overrides.pop(get_current_user_strict, None),
        require_integration_access: app.dependency_overrides.pop(require_integration_access, None),
    }
    saved_debug = app_settings.DEBUG
    # DEBUG=False removes the demo-fallback path entirely so the test
    # also catches a future revert that re-introduces the fallback in a
    # non-strict variant.
    app_settings.DEBUG = False
    try:
        async with AsyncClient(app=app, base_url="http://test") as no_auth_client:
            ts = _now_ms()
            r = await no_auth_client.post(
                f"{API_PREFIX}/track",
                json={"eventName": "page_view", "timestamp": ts, "sessionId": "s"},
            )
            assert r.status_code == 401, r.text
            r = await no_auth_client.post(
                f"{API_PREFIX}/track/batch",
                json={"events": [{"eventName": "page_view", "timestamp": ts, "sessionId": "s"}]},
            )
            assert r.status_code == 401, r.text
            for path in (
                "/metrics/onboarding",
                "/metrics/time-to-value",
                "/metrics/feature-adoption",
                "/metrics/summary",
            ):
                r = await no_auth_client.get(f"{API_PREFIX}{path}")
                assert r.status_code == 401, f"{path} should be 401, got {r.status_code}"
            r = await no_auth_client.delete(f"{API_PREFIX}/events")
            assert r.status_code == 401, r.text
    finally:
        app_settings.DEBUG = saved_debug
        for dep, original in saved.items():
            if original is not None:
                app.dependency_overrides[dep] = original


@pytest.mark.asyncio
async def test_track_returns_404_for_jwt_without_user_row():
    """A JWT-valid call without a provisioned User row returns 404 instead of
    silently recording an anonymous row. The frontend treats 404 as transient
    so events queued during lazy-provisioning are replayed once the User row
    exists, without splitting one real attempt across two backend identities."""
    from httpx import AsyncClient
    from app.api.deps import (
        get_current_user,
        get_current_user_strict,
        require_integration_access,
    )
    from app.core.security import create_access_token
    from app.main import app

    saved = {
        get_current_user: app.dependency_overrides.pop(get_current_user, None),
        get_current_user_strict: app.dependency_overrides.pop(get_current_user_strict, None),
        require_integration_access: app.dependency_overrides.pop(require_integration_access, None),
    }
    try:
        token = create_access_token({"sub": "ghost-user@example.com"})
        async with AsyncClient(app=app, base_url="http://test") as ghost_client:
            r = await ghost_client.post(
                f"{API_PREFIX}/track",
                json={
                    "eventName": "page_view",
                    "eventData": {"page": "projects"},
                    "timestamp": _now_ms(),
                    "sessionId": "ghost-sess",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 404, r.text
    finally:
        for dep, original in saved.items():
            if original is not None:
                app.dependency_overrides[dep] = original


@pytest.mark.asyncio
async def test_onboarding_skip_at_later_step_does_not_inflate_step0_dropoff(client, db_session):
    """A skip emitted from step 1 must not be charged to step 0 attrition."""
    from app.services import analytics_service

    now = datetime.now(tz=timezone.utc)
    # 5 attempts started; 4 reach step 1; 2 of those skip from step 1; 0 complete.
    for i in range(5):
        db_session.add(
            AnalyticsEvent(
                event_name="onboarding_started",
                occurred_at=now - timedelta(minutes=i),
                session_id=f"sess-{i}",
            )
        )
    for i in range(4):
        db_session.add(
            AnalyticsEvent(
                event_name="onboarding_step_completed",
                event_data={"step": 1},
                occurred_at=now - timedelta(seconds=i),
                session_id=f"sess-{i}",
            )
        )
    for i in (0, 1):
        db_session.add(
            AnalyticsEvent(
                event_name="onboarding_skipped",
                event_data={"step": 1},
                occurred_at=now,
                session_id=f"sess-{i}",
            )
        )
    await db_session.commit()

    metrics = await analytics_service.compute_onboarding_metrics(db_session)
    assert metrics.started_count == 5
    assert metrics.skipped_count == 2
    # step_0 attrition: 5 started -> 4 step_1, 0 skipped *at step 0* = 1 drop.
    # step_1 attrition: 4 step_1 -> 0 completed, 2 skipped at step 1 = 2 drop.
    # The bigger drop is at step 1, so dropOffStep should be 1, not 0.
    assert metrics.drop_off_step == 1


@pytest.mark.asyncio
async def test_onboarding_dropoff_includes_start_to_first_step_attrition(client, db_session):
    """Attempts that emit `onboarding_started` and abandon before any step
    must be reflected in `dropOffStep` as step 0. Without this, the most
    common abandonment case (immediate drop) is silently invisible."""
    from app.services import analytics_service

    now = datetime.now(tz=timezone.utc)
    # 10 attempts started, none reached the first step.
    for i in range(10):
        db_session.add(
            AnalyticsEvent(
                event_name="onboarding_started",
                occurred_at=now - timedelta(minutes=i),
                session_id=f"abandoned-{i}",
            )
        )
    await db_session.commit()

    metrics = await analytics_service.compute_onboarding_metrics(db_session)
    assert metrics.started_count == 10
    assert metrics.completed_count == 0
    assert metrics.skipped_count == 0
    assert metrics.step_completion == {}
    # Implicit step 0 must be reported as the drop-off point.
    assert metrics.drop_off_step == 0


@pytest.mark.asyncio
async def test_onboarding_drops_step_events_with_orphan_started(client, db_session):
    """A step event whose matching `started` aged out of the retention
    window must NOT contribute to stepCompletion/dropOffStep — otherwise
    the funnel reports activity for attempts that are not in startedCount."""
    from app.core.config import settings as app_settings
    from app.services import analytics_service

    app_settings.ANALYTICS_RETENTION_DAYS = 1
    now = datetime.now(tz=timezone.utc)
    # Started 5 days ago — pruned by retention.
    db_session.add(
        AnalyticsEvent(
            event_name="onboarding_started",
            occurred_at=now - timedelta(days=5),
            session_id="orphan-attempt",
        )
    )
    # Step event 2 hours ago — inside retention.
    db_session.add(
        AnalyticsEvent(
            event_name="onboarding_step_completed",
            event_data={"step": 1},
            occurred_at=now - timedelta(hours=2),
            session_id="orphan-attempt",
        )
    )
    await db_session.commit()

    metrics = await analytics_service.compute_onboarding_metrics(db_session)
    assert metrics.started_count == 0
    # Orphan step must be excluded.
    assert metrics.step_completion == {}
    assert metrics.drop_off_step is None


@pytest.mark.asyncio
async def test_metrics_require_admin_permission(client):
    """Non-admin user should receive 403 for metrics/delete endpoints."""
    from app.api.deps import get_current_user, get_current_user_strict
    from app.main import app

    class _NonAdminUser:
        id = 2
        email = "viewer@example.com"
        username = "viewer"
        full_name = "Viewer"
        is_active = True
        is_superuser = False
        mfa_enabled = False
        mfa_secret = None
        mfa_backup_codes = None

        def has_permission(self, _permission: str) -> bool:
            return False

        def has_role(self, _role: str) -> bool:
            return False

        @property
        def mfa_configured(self) -> bool:
            return False

        @property
        def remaining_backup_codes(self) -> int:
            return 0

    async def _override():
        return _NonAdminUser()

    original = app.dependency_overrides.get(get_current_user)
    original_strict = app.dependency_overrides.get(get_current_user_strict)
    app.dependency_overrides[get_current_user] = _override
    app.dependency_overrides[get_current_user_strict] = _override
    try:
        for path in (
            "/metrics/onboarding",
            "/metrics/time-to-value",
            "/metrics/feature-adoption",
            "/metrics/summary",
        ):
            r = await client.get(f"{API_PREFIX}{path}")
            assert r.status_code == 403, f"{path} should be 403 for non-admin, got {r.status_code}"

        r = await client.delete(f"{API_PREFIX}/events")
        assert r.status_code == 403
    finally:
        if original is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = original
        if original_strict is None:
            app.dependency_overrides.pop(get_current_user_strict, None)
        else:
            app.dependency_overrides[get_current_user_strict] = original_strict
