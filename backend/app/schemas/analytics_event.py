"""Pydantic schemas for usage analytics endpoints.

camelCase JSON wire format (matching the frontend AnalyticsService) is exposed
via Pydantic field aliases. snake_case attribute names are used internally.
"""

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings


class _CamelModel(BaseModel):
    """Base model that accepts/serialises camelCase via alias."""

    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
    )


class AnalyticsEventIn(_CamelModel):
    """Single analytics event payload received from the client."""

    event_name: str = Field(alias="eventName", min_length=1, max_length=128)
    event_data: Optional[Dict[str, Any]] = Field(default=None, alias="eventData")
    timestamp: int  # epoch milliseconds (UTC)
    session_id: Optional[str] = Field(default=None, alias="sessionId", max_length=128)

    @field_validator("event_name", mode="before")
    @classmethod
    def _strip_and_require_event_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("event_name must not be blank")
            return stripped
        return value

    @field_validator("event_data")
    @classmethod
    def _enforce_event_data_size(
        cls, value: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Reject oversized payloads at the boundary.

        Without an upper bound, clients could push arbitrarily large blobs
        into `event_data`, bloating the event table and the JSON parsing
        cost of every aggregation. Size is measured against the JSON-
        serialised form (the same shape that lands in the column).
        """
        if value is None:
            return value
        try:
            encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError("event_data must be JSON-serialisable")
        if len(encoded) > settings.ANALYTICS_EVENT_DATA_MAX_BYTES:
            raise ValueError(
                "event_data exceeds "
                f"{settings.ANALYTICS_EVENT_DATA_MAX_BYTES} bytes"
            )
        return value

    @field_validator("timestamp")
    @classmethod
    def _reject_far_future_timestamp(cls, value: int) -> int:
        """Reject timestamps too far in the future.

        Client-supplied clocks routinely drift by a few minutes, but events
        timestamped years ahead would silently slip past the retention
        window and skew time-bucketed metrics. We allow a configurable
        skew tolerance and reject anything beyond it.
        """
        import time

        if not isinstance(value, int) or value <= 0:
            raise ValueError("timestamp must be a positive epoch-ms integer")
        now_ms = int(time.time() * 1000)
        skew_ms = settings.ANALYTICS_MAX_FUTURE_SKEW_SECONDS * 1000
        if value > now_ms + skew_ms:
            raise ValueError(
                "timestamp is more than "
                f"{settings.ANALYTICS_MAX_FUTURE_SKEW_SECONDS}s ahead of server"
            )
        return value


class AnalyticsEventBatchIn(_CamelModel):
    """Batch payload.

    Upper bound enforced at runtime by the endpoint against
    `settings.ANALYTICS_BATCH_MAX_SIZE`. Schema keeps only the lower bound
    so the configurable limit remains the single source of truth.
    """

    events: List[AnalyticsEventIn] = Field(min_length=1)


class TrackResponse(_CamelModel):
    accepted: int
    received_at: int = Field(alias="receivedAt")  # epoch ms (server time)


class OnboardingMetricsOut(_CamelModel):
    completion_rate: float = Field(alias="completionRate")
    avg_time_to_complete_sec: Optional[float] = Field(alias="avgTimeToCompleteSec")
    drop_off_step: Optional[int] = Field(alias="dropOffStep")
    started_count: int = Field(alias="startedCount")
    completed_count: int = Field(alias="completedCount")
    skipped_count: int = Field(alias="skippedCount")
    step_completion: Dict[str, int] = Field(alias="stepCompletion")


class TimeToValueMetricsOut(_CamelModel):
    avg_to_first_sync_sec: Optional[float] = Field(alias="avgToFirstSyncSec")
    avg_to_first_project_view_sec: Optional[float] = Field(alias="avgToFirstProjectViewSec")
    avg_to_first_task_view_sec: Optional[float] = Field(alias="avgToFirstTaskViewSec")
    sample_size: int = Field(alias="sampleSize")


class FeatureAdoptionMetricsOut(_CamelModel):
    features: Dict[str, int]
    adoption_rate: float = Field(alias="adoptionRate")
    most_used: List[str] = Field(alias="mostUsed")
    least_used: List[str] = Field(alias="leastUsed")


class UsageSummaryOut(_CamelModel):
    onboarding_completion_rate: float = Field(alias="onboardingCompletionRate")
    avg_time_to_first_value: Optional[float] = Field(alias="avgTimeToFirstValue")
    feature_adoption_rate: float = Field(alias="featureAdoptionRate")
    active_users_count: int = Field(alias="activeUsersCount")
