import pytest


@pytest.mark.asyncio
async def test_list_capacity_settings_returns_empty_page(client):
    response = await client.get("/api/v1/capacity/settings", params={"project_id": 1, "skip": 0, "limit": 50})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_list_health_checks_returns_empty_page(client):
    response = await client.get(
        "/api/v1/capacity/health-checks",
        params={"project_id": 1, "skip": 0, "limit": 50},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"] == []
    assert payload["meta"]["total"] == 0


@pytest.mark.asyncio
async def test_capacity_legacy_summary_route(client):
    response = await client.get(
        "/api/v1/capacity/summary",
        params={"project_id": 1, "sprint_weeks": 2},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["team_members"] == 0
    assert payload["total_theoretical_hours"] == 0


@pytest.mark.asyncio
async def test_capacity_legacy_health_summary_route(client):
    response = await client.get(
        "/api/v1/capacity/health-summary",
        params={"project_id": 1, "period_days": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["checks_count"] == 0


@pytest.mark.asyncio
async def test_capacity_legacy_cfd_and_flow_metrics_routes(client):
    cfd_response = await client.get("/api/v1/capacity/cfd", params={"project_id": 1})
    metrics_response = await client.get(
        "/api/v1/capacity/flow-metrics",
        params={"project_id": 1, "days": 30},
    )

    assert cfd_response.status_code == 200
    assert cfd_response.json()["snapshots"] == []

    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.json()
    assert metrics_payload["avg_cycle_time_hours"] is None
    assert metrics_payload["wip_trend"] == "stable"
