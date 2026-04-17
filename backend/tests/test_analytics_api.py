from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.main import app
from app.core.database import AsyncSessionLocal
from app.models import (
    Project,
    Task,
    PullRequest,
    Sprint,
    Repository,
    ProjectRepository,
    TestResult,
    CoverageReport,
)
from app.models.traceability import Artifact
from app.services.jira_service import jira_service
from tests._sqlite_schema import reset_sqlite_schema


async def reset_database() -> None:
    await reset_sqlite_schema()


@pytest.mark.asyncio
async def test_dora_endpoint_returns_metrics():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="OPS", name="Ops Platform", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        repository = Repository(provider="github", repo_slug="org/ops-platform")
        session.add(repository)
        await session.commit()
        await session.refresh(repository)

        session.add(
            ProjectRepository(project_id=project.id, repository_id=repository.id, is_primary=True)
        )
        await session.commit()

        task_deploy = Task(
            jira_id="OPS-1",
            key="OPS-1",
            summary="Deploy microservice",
            status="Done",
            project_id=project.id,
            created_date=now - timedelta(days=3),
            resolved_date=now - timedelta(days=1)
        )
        task_incident = Task(
            jira_id="OPS-INC",
            key="OPS-INC",
            summary="Production incident",
            status="Resolved",
            task_type="Incident",
            project_id=project.id,
            created_date=now - timedelta(hours=10),
            resolved_date=now - timedelta(hours=2)
        )
        session.add_all([task_deploy, task_incident])
        await session.commit()

        pr = PullRequest(
            provider="github",
            repository_id=repository.id,
            project_id=project.id,
            number=42,
            title="Deploy OPS",
            state="merged",
            opened_at=now - timedelta(hours=8),
            merged_at=now - timedelta(hours=1),
            jira_keys=["OPS-1"],
            lead_time_hours=7.0,
            cycle_time_hours=8.0,
            rework_count=0
        )
        session.add(pr)
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analytics/projects/{project.id}/dora", params={"window_days": 30})
    assert response.status_code == 200
    data = response.json()

    assert data["deployments"] == 1
    assert data["lead_time_hours"]["median"] == pytest.approx(7.0)
    assert data["change_failure_rate"] == 0
    assert data["mean_time_to_recovery_hours"]["samples"] == 1
    assert data["totals"]["incidents"] == 1


@pytest.mark.asyncio
async def test_velocity_endpoint_aggregates_closed_sprints():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="VELOC", name="Velocity Project", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        sprint1 = Sprint(
            jira_id="SPR-1",
            name="Sprint 1",
            state="closed",
            project_id=project.id,
            start_date=now - timedelta(days=28),
            end_date=now - timedelta(days=21)
        )
        sprint2 = Sprint(
            jira_id="SPR-2",
            name="Sprint 2",
            state="closed",
            project_id=project.id,
            start_date=now - timedelta(days=21),
            end_date=now - timedelta(days=14)
        )
        session.add_all([sprint1, sprint2])
        await session.commit()
        await session.refresh(sprint1)
        await session.refresh(sprint2)

        tasks = [
            Task(
                jira_id="VELOC-1",
                key="VELOC-1",
                summary="Complete feature",
                status="Done",
                project_id=project.id,
                sprint_id=sprint1.id,
                estimate_hours=10,
                resolved_date=now - timedelta(days=20)
            ),
            Task(
                jira_id="VELOC-2",
                key="VELOC-2",
                summary="Bug fix",
                status="Done",
                project_id=project.id,
                sprint_id=sprint2.id,
                estimate_hours=6,
                resolved_date=now - timedelta(days=15)
            )
        ]
        session.add_all(tasks)
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analytics/projects/{project.id}/velocity", params={"sprints_count": 5})
    assert response.status_code == 200
    data = response.json()

    assert data["sprints_analyzed"] == 2
    assert data["average_velocity"] == pytest.approx((10 + 6) / 2, rel=1e-3)
    assert any(item["sprint_name"] == "Sprint 1" for item in data["sprint_velocities"])


@pytest.mark.asyncio
async def test_project_sprints_endpoint_filters_by_board_id(monkeypatch: pytest.MonkeyPatch):
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="BOARD", name="Board Filter Project", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        project_id = project.id

        session.add_all(
            [
                Sprint(
                    jira_id="11",
                    name="Board 11 Sprint",
                    state="closed",
                    project_id=project.id,
                    start_date=now - timedelta(days=14),
                    end_date=now - timedelta(days=7),
                ),
                Sprint(
                    jira_id="22",
                    name="Board 22 Sprint",
                    state="closed",
                    project_id=project.id,
                    start_date=now - timedelta(days=7),
                    end_date=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

    monkeypatch.setattr(
        jira_service,
        "list_sprints",
        lambda board_id: [{"id": 11}] if board_id == 11 else [],
    )

    from app.services.cache_service import cache_service

    cache_service.clear_pattern("project_sprints")

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/analytics/projects/{project_id}/sprints",
            params={"board_id": 11, "limit": 10},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1
    assert [sprint["name"] for sprint in data["sprints"]] == ["Board 11 Sprint"]


@pytest.mark.asyncio
async def test_coverage_analytics_defaults_to_all_artifact_types():
    await reset_database()

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="COV", name="Coverage Project", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        project_id = project.id

        session.add_all(
            [
                Artifact(
                    type="jira_issue",
                    source="jira",
                    external_id="COV-1",
                    display_key="COV-1",
                    title="Issue 1",
                    project_id=project_id,
                ),
                Artifact(
                    type="jira_issue",
                    source="jira",
                    external_id="COV-2",
                    display_key="COV-2",
                    title="Issue 2",
                    project_id=project_id,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/traceability/coverage-analytics",
            params={"project_id": project_id},
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["coverage"]["total_artifacts"] == 2
    assert data["coverage"]["by_type"]["jira_issue"]["total"] == 2
    assert data["quality_gates"]["details"]["requirement_coverage"]["has_requirements"] is False


@pytest.mark.asyncio
async def test_project_burndown_returns_curves():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="BRND", name="Burndown Project", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        sprint = Sprint(
            jira_id="BRND-1",
            name="Sprint BD",
            state="active",
            project_id=project.id,
            start_date=now - timedelta(days=6),
            end_date=now + timedelta(days=1)
        )
        session.add(sprint)
        await session.commit()
        await session.refresh(sprint)

        session.add_all([
            Task(
                jira_id="BRND-1",
                key="BRND-1",
                summary="Story A",
                status="Done",
                project_id=project.id,
                sprint_id=sprint.id,
                estimate_hours=8,
                resolved_date=now - timedelta(days=1)
            ),
            Task(
                jira_id="BRND-2",
                key="BRND-2",
                summary="Story B",
                status="In Progress",
                project_id=project.id,
                sprint_id=sprint.id,
                estimate_hours=5
            )
        ])
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/analytics/projects/{project.id}/burndown",
            params={"sprint_id": sprint.id}
        )
    assert response.status_code == 200
    data = response.json()

    assert data["sprint"]["name"] == "Sprint BD"
    assert data["ideal_burndown"]
    assert data["actual_burndown"]
    assert data["actual_burndown"][-1]["remaining"] <= data["ideal_burndown"][0]["ideal_remaining"]

@pytest.mark.asyncio
async def test_test_trend_endpoint_groups_failures():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                TestResult(status="passed", created_at=now - timedelta(days=1)),
                TestResult(status="failed", created_at=now - timedelta(days=1), suite="unit"),
                TestResult(status="failed", created_at=now - timedelta(days=2), suite="integration"),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/test-trend", params={"days": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["days"] == 3
    assert payload["trend"]

    trend_map = {entry["day"]: entry for entry in payload["trend"]}
    assert len(trend_map) == 2

    latest_day = max(trend_map)
    assert trend_map[latest_day]["total"] == 2
    assert trend_map[latest_day]["failed"] == 1

    oldest_day = min(trend_map)
    assert trend_map[oldest_day]["failed"] == 1


@pytest.mark.asyncio
async def test_coverage_trend_endpoint_returns_daily_averages():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                CoverageReport(
                    provider="pytest",
                    line_coverage=0.6,
                    branch_coverage=0.4,
                    created_at=now - timedelta(days=1),
                ),
                CoverageReport(
                    provider="pytest",
                    line_coverage=0.8,
                    branch_coverage=0.7,
                    created_at=now - timedelta(days=1),
                ),
                CoverageReport(
                    provider="pytest",
                    line_coverage=0.9,
                    branch_coverage=0.75,
                    created_at=now - timedelta(days=2),
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/analytics/coverage-trend", params={"days": 4})

    assert response.status_code == 200
    payload = response.json()
    assert payload["trend"]

    trend_map = {entry["day"]: entry for entry in payload["trend"]}
    assert len(trend_map) == 2

    latest = trend_map[max(trend_map)]
    assert latest["count"] == 2
    assert latest["avg_line"] == pytest.approx(0.7, rel=1e-3)
    assert latest["avg_branch"] == pytest.approx(0.55, rel=1e-3)


@pytest.mark.asyncio
async def test_project_pr_forecast_returns_average_metrics():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        repository = Repository(provider="github", repo_slug="org/project")
        session.add(repository)
        await session.commit()
        await session.refresh(repository)

        session.add_all(
            [
                PullRequest(
                    provider="github",
                    repository_id=repository.id,
                    number=1,
                    title="Add feature",
                    state="merged",
                    opened_at=now - timedelta(days=2),
                    merged_at=now - timedelta(days=1),
                    cycle_time_hours=24,
                    lead_time_hours=30,
                    time_to_first_review_hours=6,
                ),
                PullRequest(
                    provider="github",
                    repository_id=repository.id,
                    number=2,
                    title="Bugfix",
                    state="merged",
                    opened_at=now - timedelta(days=3),
                    merged_at=now - timedelta(hours=12),
                    cycle_time_hours=12,
                    lead_time_hours=18,
                    time_to_first_review_hours=3,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analytics/projects/{repository.id}/forecast/pr")

    assert response.status_code == 200
    payload = response.json()

    assert payload["total"] == 2
    assert payload["avg_cycle_time_hours"] == pytest.approx(18.0, rel=1e-3)
    assert payload["avg_lead_time_hours"] == pytest.approx(24.0, rel=1e-3)
    assert payload["avg_time_to_first_review_hours"] == pytest.approx(4.5, rel=1e-3)

@pytest.mark.asyncio
async def test_identify_project_risks_flags_multiple_categories():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="RISK", name="Risky", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        session.add_all(
            [
                Task(
                    jira_id="RISK-1",
                    key="RISK-1",
                    summary="Overdue task",
                    status="In Progress",
                    project_id=project.id,
                    due_date=now - timedelta(days=2),
                    estimate_hours=5,
                ),
                Task(
                    jira_id="RISK-2",
                    key="RISK-2",
                    summary="Blocked task",
                    status="In Progress",
                    project_id=project.id,
                    is_blocker=True,
                    estimate_hours=3,
                ),
                *(
                    Task(
                        jira_id=f"RISK-U{i}",
                        key=f"RISK-U{i}",
                        summary="Unestimated",
                        status="To Do",
                        project_id=project.id,
                    )
                    for i in range(3, 7)
                ),
                Task(
                    jira_id="RISK-OVER",
                    key="RISK-OVER",
                    summary="Budget overrun",
                    status="In Progress",
                    project_id=project.id,
                    estimate_hours=10,
                    spent_hours=60,
                ),
            ]
        )
        await session.commit()
        project_id = project.id

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analytics/projects/{project_id}/risks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["risk_level"] == "critical"
    assert payload["total_risks"] == 4

    risk_types = {item["type"] for item in payload["risks"]}
    assert {"overdue_tasks", "blocked_tasks", "unestimated_tasks", "budget_overrun"}.issubset(risk_types)


@pytest.mark.asyncio
async def test_forecast_completion_uses_velocity_and_remaining_hours():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="FORE", name="Forecast", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        sprint1 = Sprint(
            jira_id="FORE-1",
            name="Sprint A",
            state="closed",
            project_id=project.id,
            start_date=now - timedelta(days=30),
            end_date=now - timedelta(days=23),
        )
        sprint2 = Sprint(
            jira_id="FORE-2",
            name="Sprint B",
            state="closed",
            project_id=project.id,
            start_date=now - timedelta(days=22),
            end_date=now - timedelta(days=15),
        )
        session.add_all([sprint1, sprint2])
        await session.commit()
        await session.refresh(sprint1)
        await session.refresh(sprint2)

        session.add_all(
            [
                Task(
                    jira_id="FORE-TA",
                    key="FORE-TA",
                    summary="Closed work A",
                    status="Done",
                    project_id=project.id,
                    sprint_id=sprint1.id,
                    estimate_hours=20,
                ),
                Task(
                    jira_id="FORE-TB",
                    key="FORE-TB",
                    summary="Closed work B",
                    status="Done",
                    project_id=project.id,
                    sprint_id=sprint2.id,
                    estimate_hours=10,
                ),
                Task(
                    jira_id="FORE-B1",
                    key="FORE-B1",
                    summary="Backlog work",
                    status="In Progress",
                    project_id=project.id,
                    estimate_hours=12,
                ),
                Task(
                    jira_id="FORE-B2",
                    key="FORE-B2",
                    summary="More backlog",
                    status="To Do",
                    project_id=project.id,
                    estimate_hours=8,
                ),
            ]
        )
        await session.commit()
        project_id = project.id

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(f"/api/v1/analytics/projects/{project_id}/forecast")

    assert response.status_code == 200
    payload = response.json()
    assert payload["average_velocity"] == pytest.approx(15.0, rel=1e-3)
    assert payload["remaining_hours"] == pytest.approx(20.0, rel=1e-3)
    assert payload["forecast_sprints"] == pytest.approx(1.33, rel=1e-2)
