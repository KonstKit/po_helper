from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from app.core.middleware import ObservabilityMiddleware


class _DummyMetrics:
    def __init__(self) -> None:
        self.increments: List[Tuple[str, float, Dict[str, str] | None]] = []
        self.observations: List[Tuple[str, float, Dict[str, str] | None]] = []

    def inc(self, name: str, value: float = 1.0, labels: Dict[str, str] | None = None) -> None:
        self.increments.append((name, value, labels))

    def observe(self, name: str, value: float, labels: Dict[str, str] | None = None) -> None:
        self.observations.append((name, value, labels))


async def _receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


@pytest.mark.asyncio
async def test_observability_uses_route_template_and_splits_4xx_5xx(monkeypatch):
    from app.core import middleware as middleware_module

    metrics = _DummyMetrics()
    monkeypatch.setattr(middleware_module, "metrics", metrics)

    async def _app_404(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def _app_500(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    sent_messages: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    scope_404 = {
        "type": "http",
        "path": "/api/v1/projects/abc-slug",
        "method": "GET",
        "route": SimpleNamespace(path_format="/api/v1/projects/{project_id}"),
    }
    scope_500 = {
        "type": "http",
        "path": "/api/v1/projects/abc-slug",
        "method": "GET",
        "route": SimpleNamespace(path_format="/api/v1/projects/{project_id}"),
    }

    await ObservabilityMiddleware(_app_404)(scope_404, _receive, _send)
    await ObservabilityMiddleware(_app_500)(scope_500, _receive, _send)

    assert sent_messages
    assert any(
        name == "http_request_client_errors"
        and labels is not None
        and labels.get("path") == "/api/v1/projects/{project_id}"
        for name, _, labels in metrics.increments
    )
    assert any(
        name == "http_request_errors"
        and labels is not None
        and labels.get("path") == "/api/v1/projects/{project_id}"
        for name, _, labels in metrics.increments
    )
