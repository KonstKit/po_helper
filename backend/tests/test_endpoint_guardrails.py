from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.api.api_v1.endpoints.health import _record_integrations_guardrail
from app.api.api_v1.endpoints.jira import _record_boards_guardrail


class _DummyMetrics:
    def __init__(self) -> None:
        self.observations: List[Tuple[str, float, Dict[str, str] | None]] = []
        self.increments: List[Tuple[str, float, Dict[str, str] | None]] = []

    def observe(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        self.observations.append((name, value, labels))

    def inc(self, name: str, value: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        self.increments.append((name, value, labels))


def _monkeypatch_metrics(monkeypatch: Any, module_path: str) -> _DummyMetrics:
    dummy = _DummyMetrics()
    monkeypatch.setattr(module_path, dummy)
    return dummy


def test_health_integrations_guardrail_marks_slow_requests(monkeypatch: Any, caplog: Any) -> None:
    caplog.set_level(logging.WARNING)
    dummy = _monkeypatch_metrics(monkeypatch, "app.api.api_v1.endpoints.health.metrics")

    _record_integrations_guardrail(duration=2.5, status="ok", cache_hit=False)

    assert any(name == "api_endpoint_duration_seconds" for name, _, _ in dummy.observations)
    assert any(name == "api_endpoint_slow_total" for name, _, _ in dummy.increments)
    assert "health.integrations.slow" in caplog.text


def test_health_integrations_guardrail_marks_degraded_requests(
    monkeypatch: Any, caplog: Any
) -> None:
    caplog.set_level(logging.WARNING)
    dummy = _monkeypatch_metrics(monkeypatch, "app.api.api_v1.endpoints.health.metrics")

    _record_integrations_guardrail(duration=0.2, status="db_timeout", cache_hit=False)

    assert any(name == "api_endpoint_duration_seconds" for name, _, _ in dummy.observations)
    assert any(name == "api_endpoint_degraded_total" for name, _, _ in dummy.increments)
    assert "health.integrations.degraded" in caplog.text


def test_health_integrations_guardrail_does_not_mark_cache_hit_as_degraded(
    monkeypatch: Any, caplog: Any
) -> None:
    caplog.set_level(logging.WARNING)
    dummy = _monkeypatch_metrics(monkeypatch, "app.api.api_v1.endpoints.health.metrics")

    _record_integrations_guardrail(duration=0.1, status="ok", cache_hit=True)

    assert any(
        name == "api_endpoint_duration_seconds"
        and labels is not None
        and labels.get("cache_hit") == "true"
        for name, _, labels in dummy.observations
    )
    assert not any(name == "api_endpoint_degraded_total" for name, _, _ in dummy.increments)
    assert "health.integrations.degraded" not in caplog.text


def test_jira_boards_guardrail_marks_slow_requests(monkeypatch: Any, caplog: Any) -> None:
    caplog.set_level(logging.WARNING)
    dummy = _monkeypatch_metrics(monkeypatch, "app.api.api_v1.endpoints.jira.metrics")

    _record_boards_guardrail(
        "PRJ",
        duration_seconds=3.5,
        status="ok",
        boards_count=7,
    )

    assert any(name == "api_endpoint_duration_seconds" for name, _, _ in dummy.observations)
    assert any(name == "api_endpoint_slow_total" for name, _, _ in dummy.increments)
    assert "jira.project_boards.slow" in caplog.text
    assert "PRJ" in caplog.text


def test_jira_boards_guardrail_marks_error_requests(monkeypatch: Any, caplog: Any) -> None:
    caplog.set_level(logging.WARNING)
    dummy = _monkeypatch_metrics(monkeypatch, "app.api.api_v1.endpoints.jira.metrics")

    _record_boards_guardrail(
        "PRJ",
        duration_seconds=0.3,
        status="error",
        boards_count=0,
    )

    assert any(name == "api_endpoint_duration_seconds" for name, _, _ in dummy.observations)
    assert any(name == "api_endpoint_error_total" for name, _, _ in dummy.increments)
    assert "jira.project_boards.error" in caplog.text
