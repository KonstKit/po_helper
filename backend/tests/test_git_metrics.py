import sys
from pathlib import Path

import pytest
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api.api_v1.endpoints.git.metrics import (
    histogram_counts as _histogram_counts,
    calculate_pr_metrics as pull_request_metrics,
    RECENT_THROUGHPUT_DAYS,
    PR_METRICS_SAMPLE_LIMIT,
)


class _DummyResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _DummyDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_args, **_kwargs):
        return _DummyResult(self._rows)


def test_histogram_counts_basic():
    values = [1.0, 5.0, 9.0, None, 25.0, 60.0]
    thresholds = [4.0, 8.0, 12.0, 24.0, 48.0]
    counts = _histogram_counts(values, thresholds)
    assert counts == [1, 1, 1, 0, 1, 1]


@pytest.mark.asyncio
async def test_pull_request_metrics_aggregation():
    now = datetime.now(timezone.utc)
    recent_iso = (now - timedelta(hours=2)).isoformat()
    older_iso = (now - timedelta(days=30)).isoformat()

    pr_recent = SimpleNamespace(
        id=1,
        number=101,
        title="Recent PR",
        provider="github",
        cycle_time_hours=4.0,
        lead_time_hours=4.5,
        time_to_first_review_hours=2.0,
        rework_count=1,
        opened_at=recent_iso,
        created_at=recent_iso,
        merged_at=recent_iso,
        closed_at=recent_iso,
        state="merged",
        jira_keys=["ABC-1"],
    )

    pr_old = SimpleNamespace(
        id=2,
        number=102,
        title="Older PR",
        provider="github",
        cycle_time_hours=30.0,
        lead_time_hours=32.0,
        time_to_first_review_hours=None,
        rework_count=0,
        opened_at=older_iso,
        created_at=older_iso,
        merged_at=older_iso,
        closed_at=older_iso,
        state="closed",
        jira_keys=["ABC-2"],
    )

    db = _DummyDB([pr_recent, pr_old])

    metrics_all = await pull_request_metrics(
        project_id=None, provider="github", limit=None, since_days=90, db=db
    )

    assert metrics_all["total"] == 2
    assert metrics_all["cycle_samples"] == 2
    assert metrics_all["lead_samples"] == 2
    assert metrics_all["first_review_samples"] == 1
    assert metrics_all["recent_throughput"]["days"] == RECENT_THROUGHPUT_DAYS
    assert metrics_all["recent_throughput"]["merged"] == 1
    assert metrics_all["histogram"]["cycle_counts"][0] == 1
    assert metrics_all["histogram"]["cycle_counts"][4] == 1
    assert metrics_all["rework_rate"] == pytest.approx(0.5)
    assert metrics_all["sample_prs"]
    assert len(metrics_all["sample_prs"]) <= PR_METRICS_SAMPLE_LIMIT
    assert metrics_all["cache_hit"] is False

    metrics_cached = await pull_request_metrics(
        project_id=None, provider="github", limit=None, since_days=90, db=db
    )
    assert metrics_cached["cache_hit"] is True

    metrics_recent = await pull_request_metrics(
        project_id=None, provider="github", since_days=14, db=db
    )
    assert metrics_recent["total"] == 1
    assert all((sample.get("number") == 101) for sample in metrics_recent["sample_prs"])
