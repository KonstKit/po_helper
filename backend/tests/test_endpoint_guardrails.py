from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from app.api.api_v1.endpoints.health import _record_integrations_guardrail
from app.api.api_v1.endpoints.jira import _record_boards_guardrail
from app.core.config import settings


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


async def test_health_ready_returns_200_when_dependencies_are_available(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_ready() -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_redis_readiness",
        _redis_ready,
    )

    response = await client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_health_ready_returns_503_when_dependencies_are_degraded(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_degraded() -> tuple[bool, str]:
        return False, "timeout"

    async def _redis_degraded() -> tuple[bool, str]:
        return False, "error"

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_database_readiness",
        _db_degraded,
    )
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_redis_readiness",
        _redis_degraded,
    )

    response = await client.get("/api/v1/health/ready")
    data = response.json()

    assert response.status_code == 503
    assert data["status"] == "degraded"
    assert data["dependencies"]["database"]["status"] == "timeout"
    assert data["dependencies"]["redis"]["status"] == "error"


async def test_health_ready_allows_redis_not_configured_when_optional(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr(settings, "CELERY_ENABLED", False)
    monkeypatch.setattr(settings, "REDIS_URL", "")

    response = await client.get("/api/v1/health/ready")
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["dependencies"]["redis"]["status"] == "not_configured"
    assert data["dependencies"]["redis"]["required"] is False


async def test_health_ready_allows_redis_errors_when_optional(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_error() -> tuple[bool, str]:
        return False, "error"

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_redis_readiness", _redis_error)
    monkeypatch.setattr(settings, "CELERY_ENABLED", False)
    monkeypatch.setattr(settings, "REDIS_URL", "redis://unavailable:6381/0")

    response = await client.get("/api/v1/health/ready")
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["dependencies"]["redis"]["ok"] is False
    assert data["dependencies"]["redis"]["status"] == "error"
    assert data["dependencies"]["redis"]["required"] is False


async def test_health_ready_requires_redis_when_celery_enabled(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr(settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(settings, "REDIS_URL", "")

    response = await client.get("/api/v1/health/ready")
    data = response.json()

    assert response.status_code == 503
    assert data["status"] == "degraded"
    assert data["dependencies"]["redis"]["status"] == "not_configured"
    assert data["dependencies"]["redis"]["required"] is True


async def test_check_redis_readiness_uses_to_thread(monkeypatch: Any) -> None:
    from app.api.api_v1.endpoints import health as health_endpoint

    calls: dict[str, bool] = {"to_thread": False}

    async def _fake_to_thread(func, *args, **kwargs):
        calls["to_thread"] = True
        return func(*args, **kwargs)

    monkeypatch.setattr(settings, "REDIS_URL", "redis://example:6379/0")
    monkeypatch.setattr(health_endpoint, "_ping_redis_blocking", lambda _url: None)
    monkeypatch.setattr(health_endpoint.asyncio, "to_thread", _fake_to_thread)

    redis_ok, redis_status = await health_endpoint._check_redis_readiness()

    assert calls["to_thread"] is True
    assert redis_ok is True
    assert redis_status == "ok"
