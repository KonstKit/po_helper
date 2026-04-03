from __future__ import annotations

from app.core.metrics import MetricsRegistry
from app.core.middleware import _route_template_path


def test_metrics_registry_histogram_storage_is_bounded() -> None:
    registry = MetricsRegistry()
    labels = {"path": "/api/v1/projects/{project_id}", "method": "GET", "status": "200"}
    for idx in range(registry._histogram_max_samples + 250):
        registry.observe("http_request_latency_seconds", float(idx), labels=labels)

    key = registry._key("http_request_latency_seconds", labels)
    assert len(registry.histograms[key]) == registry._histogram_max_samples


def test_route_template_path_prefers_router_template() -> None:
    class _Route:
        path_format = "/api/v1/projects/{project_id}"
        path = "/api/v1/projects/{project_id}"

    assert _route_template_path({"route": _Route()}) == "/api/v1/projects/{project_id}"
