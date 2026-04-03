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


async def _async_return(value: Any) -> Any:
    return value


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
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        lambda: _async_return(
            (True, "ok", {"required": False, "queue_name": "celery", "backlog": 0})
        ),
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


async def test_health_ready_stays_200_when_queue_backlog_is_high(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _queue_backlog_high() -> tuple[bool, str, dict[str, Any]]:
        return True, "backlog_high", {"required": True, "queue_name": "celery", "backlog": 500}

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_redis_readiness", _redis_ready)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_backlog_high,
    )

    response = await client.get("/api/v1/health/ready")
    data = response.json()

    assert response.status_code == 200
    assert data["status"] == "ready"
    assert data["dependencies"]["queue"]["status"] == "backlog_high"
    assert data["dependencies"]["queue"]["ok"] is True


async def test_health_alerts_use_server_error_counter_only(
    monkeypatch: Any, client: Any
) -> None:
    from app.api.api_v1.endpoints import health as health_endpoint

    async def _queue_ok() -> tuple[bool, str, dict[str, Any]]:
        return True, "ok", {"required": False, "queue_name": "celery", "backlog": 0}

    async def _no_sync_failures(_db) -> dict[str, Any]:
        return {
            "triggered": False,
            "window_seconds": 300,
            "threshold": 5,
            "total_failures": 0,
            "by_type": {},
        }

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_celery_queue_readiness", _queue_ok)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._recent_sync_failure_alerts", _no_sync_failures)
    monkeypatch.setattr(health_endpoint.settings, "ALERT_API_ERROR_THRESHOLD", 2)
    monkeypatch.setattr(
        health_endpoint.metrics,
        "recent_counter_sum",
        lambda name, *_args, **_kwargs: {"http_request_errors": 1, "http_requests": 100}.get(name, 0),
    )

    response = await client.get("/api/v1/health/alerts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["alerts"] == []


async def test_health_alerts_include_backlog_high_signal(
    monkeypatch: Any, client: Any
) -> None:
    async def _queue_backlog_high() -> tuple[bool, str, dict[str, Any]]:
        return True, "backlog_high", {"required": True, "queue_name": "celery", "backlog": 101}

    async def _no_sync_failures(_db) -> dict[str, Any]:
        return {
            "triggered": False,
            "window_seconds": 300,
            "threshold": 5,
            "total_failures": 0,
            "by_type": {},
        }

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_backlog_high,
    )
    monkeypatch.setattr("app.api.api_v1.endpoints.health._recent_sync_failure_alerts", _no_sync_failures)

    response = await client.get("/api/v1/health/alerts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    assert any(alert["name"] == "queue_backlog_threshold" for alert in payload["alerts"])


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


async def test_health_ready_keeps_service_ready_on_queue_backlog_high(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _queue_backlog() -> tuple[bool, str, dict[str, Any]]:
        return True, "backlog_high", {"queue_name": "celery", "backlog": 123, "required": True}

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_redis_readiness", _redis_ready)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_backlog,
    )

    response = await client.get("/api/v1/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["dependencies"]["queue"]["status"] == "backlog_high"


async def test_health_alerts_include_queue_backlog_even_when_queue_check_is_ok(
    monkeypatch: Any, client: Any
) -> None:
    async def _queue_backlog() -> tuple[bool, str, dict[str, Any]]:
        return True, "backlog_high", {"queue_name": "celery", "backlog": 500, "required": True}

    async def _no_sync_failures(_db: Any) -> dict[str, Any]:
        return {
            "triggered": False,
            "window_seconds": 60,
            "threshold": 1,
            "total_failures": 0,
            "by_type": {},
        }

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_backlog,
    )
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._recent_sync_failure_alerts",
        _no_sync_failures,
    )
    monkeypatch.setattr(settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health.metrics.recent_counter_sum",
        lambda *_args, **_kwargs: 0,
    )

    response = await client.get("/api/v1/health/alerts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    names = {alert["name"] for alert in payload["alerts"]}
    assert "queue_backlog_threshold" in names


def test_recent_api_error_alert_uses_server_error_counter_only(monkeypatch: Any) -> None:
    from app.api.api_v1.endpoints import health as health_endpoint

    monkeypatch.setattr(settings, "ALERT_API_ERROR_WINDOW_SECONDS", 300)
    monkeypatch.setattr(settings, "ALERT_API_ERROR_THRESHOLD", 10)

    def _recent_counter_sum(name: str, _window: int, labels: Dict[str, str] | None = None) -> int:
        del labels
        if name == "http_request_errors":
            return 6
        if name == "http_request_client_errors":
            return 40
        if name == "http_requests":
            return 46
        return 0

    monkeypatch.setattr(health_endpoint.metrics, "recent_counter_sum", _recent_counter_sum)

    payload = health_endpoint._recent_api_error_alert()

    assert payload["triggered"] is False
    assert payload["server_error_count"] == 6
    assert payload["request_count"] == 46


async def test_health_ready_stays_ready_when_queue_backlog_is_high(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _queue_backlog_high() -> tuple[bool, str, dict[str, Any]]:
        return (
            True,
            "backlog_high",
            {
                "required": True,
                "queue_name": "celery",
                "backlog": 500,
                "backlog_threshold": 100,
                "status": "backlog_high",
            },
        )

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_redis_readiness", _redis_ready)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness", _queue_backlog_high
    )

    response = await client.get("/api/v1/health/ready")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["dependencies"]["queue"]["status"] == "backlog_high"


async def test_health_alerts_do_not_trigger_on_client_error_noise(
    monkeypatch: Any, client: Any
) -> None:
    class _FakeMetrics:
        def recent_counter_sum(self, name: str, _window_seconds: int) -> float:
            if name == "http_request_errors":
                return 0.0  # server-side errors only
            if name == "http_requests":
                return 250.0
            return 0.0

    async def _queue_ok() -> tuple[bool, str, dict[str, Any]]:
        return (
            True,
            "ok",
            {"required": True, "queue_name": "celery", "backlog": 0, "backlog_threshold": 100},
        )

    async def _sync_ok(_db: Any) -> dict[str, Any]:
        return {
            "triggered": False,
            "window_seconds": 3600,
            "threshold": 5,
            "total_failures": 0,
            "by_type": {},
        }

    monkeypatch.setattr("app.api.api_v1.endpoints.health.metrics", _FakeMetrics())
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_celery_queue_readiness", _queue_ok)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._recent_sync_failure_alerts", _sync_ok)

    response = await client.get("/api/v1/health/alerts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["alerts"] == []


async def test_health_ready_degrades_when_queue_probe_fails(
    monkeypatch: Any, client: Any
) -> None:
    async def _db_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _redis_ready() -> tuple[bool, str]:
        return True, "ok"

    async def _queue_probe_error() -> tuple[bool, str, dict[str, Any]]:
        return False, "probe_error", {"required": True, "queue_name": "celery", "backlog": 0}

    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_database_readiness", _db_ready)
    monkeypatch.setattr("app.api.api_v1.endpoints.health._check_redis_readiness", _redis_ready)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_probe_error,
    )

    response = await client.get("/api/v1/health/ready")
    payload = response.json()

    assert response.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["queue"]["status"] == "probe_error"


async def test_health_alerts_include_queue_probe_unavailable_signal(
    monkeypatch: Any, client: Any
) -> None:
    async def _queue_probe_error() -> tuple[bool, str, dict[str, Any]]:
        return False, "probe_error", {"required": True, "queue_name": "celery", "backlog": 0}

    async def _no_sync_failures(_db: Any) -> dict[str, Any]:
        return {
            "triggered": False,
            "window_seconds": 3600,
            "threshold": 5,
            "total_failures": 0,
            "by_type": {},
        }

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health._check_celery_queue_readiness",
        _queue_probe_error,
    )
    monkeypatch.setattr("app.api.api_v1.endpoints.health._recent_sync_failure_alerts", _no_sync_failures)
    monkeypatch.setattr(settings, "CELERY_ENABLED", True)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.health.metrics.recent_counter_sum",
        lambda *_args, **_kwargs: 0,
    )

    response = await client.get("/api/v1/health/alerts")
    payload = response.json()

    assert response.status_code == 200
    assert payload["status"] == "degraded"
    names = {alert["name"] for alert in payload["alerts"]}
    assert "queue_probe_unavailable" in names
