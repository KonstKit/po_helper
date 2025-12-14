from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient

from app.main import app
from app.core.database import AsyncSessionLocal, Base, engine
from app.models import Project, Task


async def reset_database() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.mark.asyncio
async def test_value_metrics_endpoint_calculates_roi_and_sums():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="VAL", name="Value Project", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        session.add_all(
            [
                Task(
                    jira_id="VAL-1",
                    key="VAL-1",
                    summary="Delivered feature",
                    status="Done",
                    project_id=project.id,
                    value_delivered=True,
                    business_value=100.0,
                    spent_hours=10.0,
                    created_date=now - timedelta(days=3),
                    resolved_date=now - timedelta(days=1),
                ),
                Task(
                    jira_id="VAL-2",
                    key="VAL-2",
                    summary="Another delivered",
                    status="Done",
                    project_id=project.id,
                    value_delivered=True,
                    business_value=50.0,
                    spent_hours=5.0,
                    created_date=now - timedelta(days=2),
                    resolved_date=now - timedelta(hours=2),
                ),
                Task(
                    jira_id="VAL-3",
                    key="VAL-3",
                    summary="Not delivered yet",
                    status="In Progress",
                    project_id=project.id,
                    value_delivered=False,
                    business_value=40.0,
                    spent_hours=2.0,
                    created_date=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/analytics/projects/{project.id}/value-metrics")

    assert resp.status_code == 200
    data = resp.json()
    assert data["value_delivered"] == pytest.approx(150.0, rel=1e-3)
    assert data["total_spent_hours"] == pytest.approx(17.0, rel=1e-3)
    assert data["roi"] == pytest.approx(150.0 / 17.0, rel=1e-3)
    assert data["total_value"] == pytest.approx(190.0, rel=1e-3)


@pytest.mark.asyncio
async def test_team_health_endpoint_returns_counts_and_cycles():
    await reset_database()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        project = Project(jira_key="HEALTH", name="Wellbeing", status="active")
        session.add(project)
        await session.commit()
        await session.refresh(project)

        session.add_all(
            [
                # Done task (48h cycle time)
                Task(
                    jira_id="HEALTH-1",
                    key="HEALTH-1",
                    summary="Complete A",
                    status="Done",
                    project_id=project.id,
                    estimate_hours=8.0,
                    spent_hours=7.5,
                    created_date=now - timedelta(days=3),
                    resolved_date=now - timedelta(days=1),
                ),
                # Done task (approx 46h)
                Task(
                    jira_id="HEALTH-2",
                    key="HEALTH-2",
                    summary="Complete B",
                    status="Closed",
                    project_id=project.id,
                    estimate_hours=6.0,
                    spent_hours=6.0,
                    created_date=now - timedelta(days=2),
                    resolved_date=now - timedelta(hours=2),
                ),
                # In progress, overdue and blocker
                Task(
                    jira_id="HEALTH-3",
                    key="HEALTH-3",
                    summary="Work C",
                    status="In Progress",
                    project_id=project.id,
                    estimate_hours=5.0,
                    spent_hours=2.0,
                    is_blocker=True,
                    due_date=now - timedelta(days=1),
                    created_date=now - timedelta(days=2),
                ),
                # Backlog
                Task(
                    jira_id="HEALTH-4",
                    key="HEALTH-4",
                    summary="Todo D",
                    status="To Do",
                    project_id=project.id,
                    estimate_hours=4.0,
                ),
            ]
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/v1/analytics/projects/{project.id}/team-health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert data["done"] == 2
    assert data["in_progress"] == 1
    assert data["backlog"] == 1
    assert data["blockers"] == 1
    assert data["overdue"] == 1
    # completion_rate two of four
    assert data["completion_rate"] == pytest.approx(0.5, rel=1e-3)
    # sums
    assert data["estimate_hours"] == pytest.approx(23.0, rel=1e-3)
    assert data["spent_hours"] == pytest.approx(15.5, rel=1e-3)
    # cycle samples should be 2 (two done tasks)
    assert data["cycle_samples"] == 2

