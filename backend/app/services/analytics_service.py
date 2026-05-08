"""Service layer for product usage analytics.

Persists analytics events into the `analytics_event` table and computes
aggregated metrics (onboarding, time-to-value, feature adoption, summary).

Aggregation is intentionally done in Python after a narrow SQL select to keep
the implementation portable across PostgreSQL and SQLite (used in tests).
Volumes are expected to be modest for a starter installation.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analytics import AnalyticsEvent
from app.models.user import User
from app.schemas.analytics_event import (
    AnalyticsEventIn,
    FeatureAdoptionMetricsOut,
    OnboardingMetricsOut,
    TimeToValueMetricsOut,
    UsageSummaryOut,
)
from app.utils.db_operations import transactional_session

logger = logging.getLogger(__name__)


# Known event names. Frontend keeps these in sync (see analytics.ts).
EVENT_ONBOARDING_STARTED = "onboarding_started"
EVENT_ONBOARDING_STEP = "onboarding_step_completed"
EVENT_ONBOARDING_COMPLETED = "onboarding_completed"
EVENT_ONBOARDING_SKIPPED = "onboarding_skipped"
EVENT_TIME_TO_VALUE = "time_to_value_milestone"
EVENT_PAGE_VIEW = "page_view"

# Frontend feature pages (see FeatureAdoptionMetrics in analytics.ts).
# Must stay in sync with the first-path-segment routes registered in App.tsx
# that PageViewTracker emits as `page_view` events.
FEATURE_PAGES = (
    "dashboard",
    "projects",
    "tasks",
    "analytics",
    "knowledge",
    "quality",
    "testing",
    "traceability",
    "jira-fields",
    "sprint-capacity",
)


def _ms_to_datetime(epoch_ms: int) -> datetime:
    """Convert frontend epoch-ms timestamp to a tz-aware UTC datetime.

    Out-of-range or malformed values fall back to "now" rather than letting
    `datetime.fromtimestamp` raise `OverflowError`/`OSError` — which would
    bubble up as 500 from /track* and put the frontend retry loop into a
    permanent stuck state on the bad event. Range covers 1970-01-01 to
    year ~9999 in milliseconds.
    """
    if not isinstance(epoch_ms, int) or epoch_ms <= 0:
        return datetime.now(tz=timezone.utc)
    if epoch_ms > 253_402_300_799_000:  # year 9999-12-31T23:59:59 in ms
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return datetime.now(tz=timezone.utc)


def _to_model(event_in: AnalyticsEventIn, *, user_id: Optional[int]) -> AnalyticsEvent:
    return AnalyticsEvent(
        event_name=event_in.event_name,
        event_data=event_in.event_data,
        occurred_at=_ms_to_datetime(event_in.timestamp),
        user_id=user_id,
        session_id=event_in.session_id,
    )


async def record_event(
    db: AsyncSession,
    event_in: AnalyticsEventIn,
    *,
    user_id: Optional[int],
) -> AnalyticsEvent:
    event = _to_model(event_in, user_id=user_id)
    try:
        async with transactional_session(
            db, error_message="record_event", log_errors=False
        ):
            db.add(event)
    except IntegrityError:
        # User row may not exist yet (e.g. lazy provisioning, external auth).
        # Persist as session-only event rather than failing the request.
        logger.warning(
            "record_event: user_id=%s violates FK; falling back to session-only",
            user_id,
        )
        event = _to_model(event_in, user_id=None)
        async with transactional_session(db, error_message="record_event_no_user"):
            db.add(event)
    await db.refresh(event)
    return event


async def record_events_batch(
    db: AsyncSession,
    events_in: Sequence[AnalyticsEventIn],
    *,
    user_id: Optional[int],
) -> int:
    rows = [_to_model(ev, user_id=user_id) for ev in events_in]
    try:
        async with transactional_session(
            db, error_message="record_events_batch", log_errors=False
        ):
            db.add_all(rows)
    except IntegrityError:
        logger.warning(
            "record_events_batch: user_id=%s violates FK; falling back to session-only",
            user_id,
        )
        rows = [_to_model(ev, user_id=None) for ev in events_in]
        async with transactional_session(
            db, error_message="record_events_batch_no_user"
        ):
            db.add_all(rows)
    return len(rows)


async def clear_events(db: AsyncSession) -> int:
    """Delete all analytics events. Returns the row count."""
    async with transactional_session(db, error_message="clear_events"):
        result = await db.execute(delete(AnalyticsEvent))
    return int(result.rowcount or 0)


# ------------------------------ Aggregations ------------------------------


def _identity(event: AnalyticsEvent) -> Optional[str]:
    """Stable identity for per-user metrics (e.g. feature adoption).

    Prefers user_id so multiple browser sessions of the same authenticated
    user collapse to one identity for adoption-style aggregations.
    """
    if event.user_id is not None:
        return f"u:{event.user_id}"
    if event.session_id:
        return f"s:{event.session_id}"
    return None


def _attempt_identity(event: AnalyticsEvent) -> Optional[str]:
    """Per-attempt identity for funnel-style metrics like onboarding.

    Onboarding aggregation must NOT collapse multiple attempts (refresh
    mid-setup, retry after skip) into a single timeline. The frontend mints
    a fresh session_id per browser session, so we key by session_id and
    namespace by user_id to avoid cross-user collisions on shared session
    ids (extremely unlikely, but cheap to prevent).
    """
    if not event.session_id:
        return None
    if event.user_id is not None:
        return f"u:{event.user_id}|s:{event.session_id}"
    return f"s:{event.session_id}"


def _retention_cutoff() -> Optional[datetime]:
    """Lower bound for metric aggregations, or None when retention is disabled.

    Bounds aggregation queries to `ANALYTICS_RETENTION_DAYS` so that
    /metrics/* stays O(retention window) regardless of total event volume.
    Older events still exist in the table until a cleanup task removes them
    (or until DELETE /events is called), but they are not scanned here.

    `ANALYTICS_RETENTION_DAYS=0` (or negative) disables the bound entirely so
    the metrics endpoints stay consistent with the cleanup task, which already
    treats 0 as "keep everything".
    """
    days = int(settings.ANALYTICS_RETENTION_DAYS)
    if days <= 0:
        return None
    return datetime.now(tz=timezone.utc) - timedelta(days=days)


async def _fetch_events_by_name(
    db: AsyncSession, names: Iterable[str]
) -> List[AnalyticsEvent]:
    stmt = select(AnalyticsEvent).where(AnalyticsEvent.event_name.in_(list(names)))
    cutoff = _retention_cutoff()
    if cutoff is not None:
        stmt = stmt.where(AnalyticsEvent.occurred_at >= cutoff)
    stmt = stmt.order_by(AnalyticsEvent.occurred_at.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def compute_onboarding_metrics(db: AsyncSession) -> OnboardingMetricsOut:
    events = await _fetch_events_by_name(
        db,
        [
            EVENT_ONBOARDING_STARTED,
            EVENT_ONBOARDING_STEP,
            EVENT_ONBOARDING_COMPLETED,
            EVENT_ONBOARDING_SKIPPED,
        ],
    )

    # Onboarding is a funnel keyed by attempt (session), not by user. A
    # single user that refreshes mid-setup or retries after skip starts a
    # fresh session and should appear as a separate attempt — otherwise
    # startedCount/completedCount/avgTimeToCompleteSec are skewed.
    started: dict[str, datetime] = {}
    completed: dict[str, datetime] = {}
    skipped: set[str] = set()
    step_counts: dict[int, set[str]] = defaultdict(set)
    # Track at which step each skip happened. OnboardingWizard emits the
    # active step in the event payload; absent values default to step 0.
    skipped_per_step: dict[int, set[str]] = defaultdict(set)

    for ev in events:
        ident = _attempt_identity(ev)
        if ident is None:
            continue
        if ev.event_name == EVENT_ONBOARDING_STARTED:
            started.setdefault(ident, ev.occurred_at)
        elif ev.event_name == EVENT_ONBOARDING_COMPLETED:
            completed.setdefault(ident, ev.occurred_at)
        elif ev.event_name == EVENT_ONBOARDING_SKIPPED:
            skipped.add(ident)
            skip_step_raw = (ev.event_data or {}).get("step")
            skip_step = skip_step_raw if isinstance(skip_step_raw, int) else 0
            skipped_per_step[skip_step].add(ident)
        elif ev.event_name == EVENT_ONBOARDING_STEP:
            step = (ev.event_data or {}).get("step")
            if isinstance(step, int):
                step_counts[step].add(ident)

    # Funnel counts must share the same population, otherwise a `completed`,
    # `skipped`, or step event whose matching `started` fell just outside
    # the retention window would inflate `completedCount`/`skippedCount`/
    # `stepCompletion`/`dropOffStep` without a matching `started`, producing
    # impossible funnels like started=0 / completed>0. Drop orphans up-front.
    started_idents = set(started.keys())
    completed = {k: v for k, v in completed.items() if k in started_idents}
    skipped = {k for k in skipped if k in started_idents}
    step_counts = {
        step: {ident for ident in idents if ident in started_idents}
        for step, idents in step_counts.items()
    }
    # Drop empty step buckets so attrition does not see ghost zero-rows.
    step_counts = {step: idents for step, idents in step_counts.items() if idents}
    skipped_per_step = {
        step: {ident for ident in idents if ident in started_idents}
        for step, idents in skipped_per_step.items()
    }

    started_count = len(started)
    completed_count = len(completed)
    skipped_count = len(skipped)
    completed_attributable = len(set(completed.keys()))
    completion_rate = (
        (completed_attributable / started_count) if started_count else 0.0
    )

    durations: List[float] = []
    for ident, started_at in started.items():
        completed_at = completed.get(ident)
        if completed_at and completed_at >= started_at:
            durations.append((completed_at - started_at).total_seconds())
    avg_duration = sum(durations) / len(durations) if durations else None

    step_completion = {str(k): len(v) for k, v in sorted(step_counts.items())}

    # Drop-off step is the step with the largest attrition to the *next*
    # funnel stage — where users actually abandon onboarding — NOT simply
    # the step with the lowest completion count (always the last step in
    # a monotonically decreasing funnel and therefore uninformative).
    #
    # The funnel includes an implicit "step 0" representing
    # `onboarding_started`. Without it, attempts that emit `started` and
    # then abandon before any `onboarding_step_completed` event never
    # contribute to drop-off, and the most common drop-off case
    # (start → first step) is silently dropped.
    #
    # For the last observed step, the natural successor is `completed`,
    # so a flow `start -> step1 -> step2 -> completed` reports attrition
    # for step2 as `step2_count - completed_count`. Without this, every
    # successful funnel would point at its own last step.
    drop_off_step: Optional[int] = None
    sorted_steps = sorted(step_counts.items(), key=lambda kv: kv[0])
    funnel: List[tuple[int, int]] = [(0, started_count)]
    funnel.extend((step, len(users)) for step, users in sorted_steps)
    if len(funnel) > 1 or started_count > 0:
        attritions: List[tuple[int, int]] = []
        for i, (step, count) in enumerate(funnel):
            if i + 1 < len(funnel):
                next_count = funnel[i + 1][1]
            else:
                next_count = completed_count
            # Subtract attempts that explicitly skipped *at this step* —
            # they are a terminal branch out of the funnel, not a
            # drop-off between this step and the next. A skip emitted
            # from step 1 should not pollute the start→step1 attrition,
            # and a skip from step 0 should not be charged to a later
            # step's attrition.
            skipped_at_step = len(skipped_per_step.get(step, set()))
            attrition = max(0, count - next_count - skipped_at_step)
            attritions.append((step, attrition))
        # Tie-break on smallest step index for determinism. If every
        # attrition is 0 (perfect funnel), report None — there is no
        # meaningful drop-off step to flag.
        max_attrition = max(attritions, key=lambda kv: (kv[1], -kv[0]))
        drop_off_step = max_attrition[0] if max_attrition[1] > 0 else None

    return OnboardingMetricsOut(
        completion_rate=completion_rate,
        avg_time_to_complete_sec=avg_duration,
        drop_off_step=drop_off_step,
        started_count=started_count,
        completed_count=completed_count,
        skipped_count=skipped_count,
        step_completion=step_completion,
    )


async def compute_time_to_value(db: AsyncSession) -> TimeToValueMetricsOut:
    """Compute TTV using server-side `users.created_at` as baseline.

    Anonymous events (without user_id) are excluded — there is no reliable
    way to back-derive an account-creation moment for them. Client-emitted
    `accountCreatedAt` milestones are intentionally ignored: the frontend
    sets that value from localStorage on first browser load, so it would
    artificially reset for returning users on a new browser or after a
    `localStorage.clear()`, biasing TTV toward zero.

    `sample_size` counts only users with at least one milestone that
    actually contributes to a returned average — otherwise the dashboard
    would report a non-zero sample with all averages `null` (e.g. for
    users who only emitted `accountCreatedAt`/`firstLoginAt`).
    """
    relevant_milestones = {
        "firstSyncAt",
        "firstProjectViewedAt",
        "firstTaskViewedAt",
    }
    events = await _fetch_events_by_name(db, [EVENT_TIME_TO_VALUE])

    first_per_milestone: dict[str, dict[int, datetime]] = defaultdict(dict)
    user_ids: set[int] = set()
    for ev in events:
        if ev.user_id is None:
            continue
        milestone = (ev.event_data or {}).get("milestone")
        if not isinstance(milestone, str) or milestone not in relevant_milestones:
            continue
        first_per_milestone[milestone].setdefault(ev.user_id, ev.occurred_at)
        user_ids.add(ev.user_id)

    if not user_ids:
        return TimeToValueMetricsOut(
            avg_to_first_sync_sec=None,
            avg_to_first_project_view_sec=None,
            avg_to_first_task_view_sec=None,
            sample_size=0,
        )

    baseline_q = select(User.id, User.created_at).where(User.id.in_(user_ids))
    baselines: dict[int, datetime] = {
        uid: created_at
        for uid, created_at in (await db.execute(baseline_q)).all()
    }

    contributing_users: set[int] = set()

    def _avg_delta(milestone_key: str) -> Optional[float]:
        target = first_per_milestone.get(milestone_key, {})
        deltas: List[float] = []
        for user_id, target_at in target.items():
            base_at = baselines.get(user_id)
            if base_at and target_at >= base_at:
                deltas.append((target_at - base_at).total_seconds())
                contributing_users.add(user_id)
        return sum(deltas) / len(deltas) if deltas else None

    avg_first_sync = _avg_delta("firstSyncAt")
    avg_first_project = _avg_delta("firstProjectViewedAt")
    avg_first_task = _avg_delta("firstTaskViewedAt")

    # `sample_size` reflects users who actually contributed at least one
    # data point to a returned average. Users whose milestones predate
    # `users.created_at` (e.g. client clock skew) are excluded from every
    # delta and must not inflate the sample.
    return TimeToValueMetricsOut(
        avg_to_first_sync_sec=avg_first_sync,
        avg_to_first_project_view_sec=avg_first_project,
        avg_to_first_task_view_sec=avg_first_task,
        sample_size=len(contributing_users),
    )


async def compute_feature_adoption(db: AsyncSession) -> FeatureAdoptionMetricsOut:
    events = await _fetch_events_by_name(db, [EVENT_PAGE_VIEW])

    feature_users: dict[str, set[str]] = {feature: set() for feature in FEATURE_PAGES}
    user_features: dict[str, set[str]] = defaultdict(set)
    # Track every page-viewing identity, including users who only hit routes
    # outside FEATURE_PAGES (e.g. /settings, /profile). They must remain in
    # the adoption denominator — otherwise adoption_rate is averaged only
    # over feature-touchers and overstates real adoption.
    all_idents: set[str] = set()
    for ev in events:
        ident = _identity(ev)
        if ident is None:
            continue
        all_idents.add(ident)
        page = (ev.event_data or {}).get("page")
        if not isinstance(page, str):
            continue
        if page in feature_users:
            feature_users[page].add(ident)
            user_features[ident].add(page)

    features = {feature: len(users) for feature, users in feature_users.items()}

    # `adoption_rate` measures user-level adoption: for each active user,
    # what fraction of tracked features did they touch? Then average across
    # users. Users with zero feature touches contribute 0 to the average;
    # without including them the rate is biased upward.
    if all_idents and FEATURE_PAGES:
        feature_count = len(FEATURE_PAGES)
        per_user_rates = [
            len(user_features.get(ident, set())) / feature_count for ident in all_idents
        ]
        adoption_rate = sum(per_user_rates) / len(per_user_rates)
    else:
        adoption_rate = 0.0

    # `most_used` filters out zero-count features (claiming a feature is the
    # "most used" with 0 visits would be misleading). `least_used` deliberately
    # includes zero-count features — that is the signal PMs look for. Ties
    # break by FEATURE_PAGES order (stable sort over insertion-ordered dict).
    sorted_desc = sorted(features.items(), key=lambda kv: kv[1], reverse=True)
    sorted_asc = sorted(features.items(), key=lambda kv: kv[1])
    most_used = [name for name, cnt in sorted_desc if cnt > 0][:3]
    least_used = [name for name, _cnt in sorted_asc[:3]]

    return FeatureAdoptionMetricsOut(
        features=features,
        adoption_rate=adoption_rate,
        most_used=most_used,
        least_used=least_used,
    )


async def compute_summary(db: AsyncSession) -> UsageSummaryOut:
    onboarding = await compute_onboarding_metrics(db)
    feature = await compute_feature_adoption(db)
    ttv = await compute_time_to_value(db)

    cutoff = _retention_cutoff()
    distinct_users_q = select(func.count(distinct(AnalyticsEvent.user_id))).where(
        AnalyticsEvent.user_id.is_not(None)
    )
    distinct_sessions_q = select(func.count(distinct(AnalyticsEvent.session_id))).where(
        AnalyticsEvent.session_id.is_not(None),
        AnalyticsEvent.user_id.is_(None),
    )
    if cutoff is not None:
        distinct_users_q = distinct_users_q.where(AnalyticsEvent.occurred_at >= cutoff)
        distinct_sessions_q = distinct_sessions_q.where(
            AnalyticsEvent.occurred_at >= cutoff
        )
    user_count = (await db.execute(distinct_users_q)).scalar() or 0
    anon_session_count = (await db.execute(distinct_sessions_q)).scalar() or 0
    active = int(user_count) + int(anon_session_count)

    return UsageSummaryOut(
        onboarding_completion_rate=onboarding.completion_rate,
        avg_time_to_first_value=ttv.avg_to_first_sync_sec,
        feature_adoption_rate=feature.adoption_rate,
        active_users_count=active,
    )
