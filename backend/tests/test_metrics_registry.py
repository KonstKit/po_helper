from app.core.metrics import MetricsRegistry


def test_histogram_storage_is_bounded() -> None:
    registry = MetricsRegistry()
    max_samples = registry._histogram_max_samples

    for idx in range(max_samples + 500):
        registry.observe("http_request_latency_seconds", float(idx), labels={"path": "/x"})

    key = registry._key("http_request_latency_seconds", {"path": "/x"})
    assert len(registry.histograms[key]) == max_samples


def test_prometheus_export_includes_quantiles_for_histograms() -> None:
    registry = MetricsRegistry()
    for value in (0.1, 0.2, 0.3, 0.4, 0.5):
        registry.observe("latency_seconds", value, labels={"path": "/health"})

    payload = registry.export_prometheus()

    assert 'latency_seconds{path="/health",quantile="0.5"}' in payload
    assert 'latency_seconds{path="/health",quantile="0.95"}' in payload
    assert 'latency_seconds{path="/health",quantile="0.99"}' in payload
    assert 'latency_seconds_count{path="/health"} 5' in payload
