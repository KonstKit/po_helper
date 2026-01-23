import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.analytics_utils import calculate_dora_metrics


class DummyPR:
    def __init__(self, lead=None, cycle=None, rework=0, state="merged"):
        self.lead_time_hours = lead
        self.cycle_time_hours = cycle
        self.rework_count = rework
        self.state = state


class DummyIncident:
    def __init__(self, created: datetime, resolved: datetime | None):
        self.created_date = created
        self.resolved_date = resolved


@pytest.mark.parametrize(
    "deployments, incidents, window, expected_freq",
    [
        ([DummyPR(lead=10)], [], 10, 0.1),
        ([DummyPR(lead=5), DummyPR(lead=7)], [], 14, (2 / 14)),
    ],
)
def test_calculate_dora_metrics_frequency(deployments, incidents, window, expected_freq):
    metrics = calculate_dora_metrics(deployments, incidents, window)
    assert math.isclose(metrics["deployment_frequency_per_day"], round(expected_freq, 3))
    assert metrics["lead_time_hours"]["samples"] == len(deployments)


def test_calculate_dora_metrics_failure_rate_and_percentiles():
    prs = [
        DummyPR(lead=4, rework=1),  # failure via rework
        DummyPR(lead=8, state="reverted"),  # failure via state
        DummyPR(lead=12),
    ]
    incidents = []
    metrics = calculate_dora_metrics(prs, incidents, window_days=30)
    assert metrics["change_failure_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert metrics["lead_time_hours"]["median"] == 8
    assert metrics["lead_time_hours"]["p90"] >= metrics["lead_time_hours"]["median"]


def test_calculate_dora_metrics_mttr():
    now = datetime.now(timezone.utc)
    incidents = [
        DummyIncident(now - timedelta(hours=5), now),
        DummyIncident(now - timedelta(hours=10), now - timedelta(hours=6)),
    ]
    metrics = calculate_dora_metrics([DummyPR(lead=3)], incidents, window_days=7)
    assert metrics["mean_time_to_recovery_hours"]["samples"] == 2
    assert metrics["mean_time_to_recovery_hours"]["average"] == pytest.approx(4.5)
    assert metrics["mean_time_to_recovery_hours"]["median"] == pytest.approx(4.5)
