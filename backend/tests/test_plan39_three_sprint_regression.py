from datetime import datetime, timedelta, timezone

import pytest

from app.models import Project, Sprint, Task


@pytest.mark.asyncio
async def test_plan39_three_sprint_regression_pack(client, db_session):
    now = datetime.now(timezone.utc)

    project = Project(jira_key="P39", name="Plan 39 Regression", status="active")
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    sprint_1 = Sprint(
        jira_id="P39-SPR-1",
        name="Sprint 1",
        state="closed",
        project_id=project.id,
        start_date=now - timedelta(days=30),
        end_date=now - timedelta(days=23),
    )
    sprint_2 = Sprint(
        jira_id="P39-SPR-2",
        name="Sprint 2",
        state="closed",
        project_id=project.id,
        start_date=now - timedelta(days=22),
        end_date=now - timedelta(days=15),
    )
    sprint_3 = Sprint(
        jira_id="P39-SPR-3",
        name="Sprint 3",
        state="active",
        project_id=project.id,
        start_date=now - timedelta(days=7),
        end_date=now + timedelta(days=7),
    )
    db_session.add_all([sprint_1, sprint_2, sprint_3])
    await db_session.commit()
    await db_session.refresh(sprint_1)
    await db_session.refresh(sprint_2)
    await db_session.refresh(sprint_3)

    db_session.add_all(
        [
            Task(
                jira_id="P39-1",
                key="P39-1",
                summary="Sprint 1 done",
                status="Done",
                project_id=project.id,
                sprint_id=sprint_1.id,
                estimate_hours=5,
                resolved_date=now - timedelta(days=24),
            ),
            Task(
                jira_id="P39-2",
                key="P39-2",
                summary="Sprint 2 done",
                status="Done",
                project_id=project.id,
                sprint_id=sprint_2.id,
                estimate_hours=8,
                resolved_date=now - timedelta(days=16),
            ),
            Task(
                jira_id="P39-3",
                key="P39-3",
                summary="Sprint 3 in progress",
                status="In Progress",
                project_id=project.id,
                sprint_id=sprint_3.id,
                estimate_hours=3,
                assignee_email="owner@example.com",
            ),
        ]
    )
    await db_session.commit()

    velocity_response = await client.get(
        f"/api/v1/analytics/projects/{project.id}/velocity",
        params={"sprints_count": 5},
    )
    burndown_response = await client.get(
        f"/api/v1/analytics/projects/{project.id}/burndown",
        params={"sprint_id": sprint_3.id},
    )
    wip_response = await client.get(f"/api/v1/analytics/sprints/{sprint_3.id}/wip-status")

    assert velocity_response.status_code == 200
    assert burndown_response.status_code == 200
    assert wip_response.status_code == 200

    velocity_payload = velocity_response.json()
    burndown_payload = burndown_response.json()
    wip_payload = wip_response.json()

    assert velocity_payload["sprints_analyzed"] == 2
    assert {entry["sprint_name"] for entry in velocity_payload["sprint_velocities"]} == {
        "Sprint 1",
        "Sprint 2",
    }
    assert burndown_payload["ideal_burndown"]
    assert burndown_payload["actual_burndown"]
    assert wip_payload["total_active"] == 1
    assert wip_payload["assignees"]
