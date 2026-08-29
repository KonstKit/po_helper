import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Project, Task
from app.api.api_v1.endpoints.analytics import get_project_team_health

DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:
    engine = create_async_engine(DATABASE_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async_session_factory = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with async_session_factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_team_health_metrics(async_session: AsyncSession):
    project = Project(jira_key="TEST", name="Test Project", status="active")
    async_session.add(project)
    await async_session.flush()

    now = datetime.now(timezone.utc)

    async_session.add_all(
        [
            Task(
                jira_id="TASK-1",
                key="TASK-1",
                summary="Completed work",
                status="Done",
                project_id=project.id,
                created_date=now - timedelta(days=5),
                resolved_date=now - timedelta(days=1),
                estimate_hours=5.0,
                spent_hours=6.0,
            ),
            Task(
                jira_id="TASK-2",
                key="TASK-2",
                summary="Working item",
                status="In Progress",
                project_id=project.id,
                estimate_hours=3.0,
                spent_hours=1.5,
                is_blocker=True,
            ),
            Task(
                jira_id="TASK-3",
                key="TASK-3",
                summary="Queued",
                status="Todo",
                project_id=project.id,
                due_date=now - timedelta(days=2),
            ),
        ]
    )
    await async_session.commit()

    result = await get_project_team_health(project.id, db=async_session)

    assert result["total"] == 3
    assert result["done"] == 1
    assert result["in_progress"] == 1
    assert result["backlog"] == 1
    assert result["blockers"] == 1
    assert result["overdue"] == 1
    assert result["completion_rate"] == pytest.approx(1 / 3, rel=1e-3)
    assert result["estimate_hours"] == pytest.approx(8.0)
    assert result["spent_hours"] == pytest.approx(7.5)
    assert result["cycle_samples"] == 1
    assert result["avg_cycle_time_hours"] is not None


@pytest.mark.asyncio
async def test_team_health_no_tasks(async_session: AsyncSession):
    project = Project(jira_key="EMPTY", name="Empty Project", status="active")
    async_session.add(project)
    await async_session.commit()

    result = await get_project_team_health(project.id, db=async_session)
    assert result["total"] == 0
    assert result["completion_rate"] == 0.0
