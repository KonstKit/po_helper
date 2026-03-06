import asyncio
from io import BytesIO
import zipfile

import pytest

from app.services.task_manager import task_manager


async def _poll_task_status(client, task_id: str, attempts: int = 40, delay: float = 0.05) -> dict:
    last_payload = None
    for _ in range(attempts):
        response = await client.get(f"/api/v1/async-tasks/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last_payload = response.json()
        if last_payload["status"] == "completed":
            return last_payload
        assert last_payload["status"] in {"pending", "running"}, last_payload
        await asyncio.sleep(delay)
    raise AssertionError(f"Task {task_id} did not complete in time: {last_payload}")


@pytest.mark.asyncio
async def test_projects_tasks_sequence_async_export_flow(client):
    task_manager._tasks.clear()

    project_response = await client.post(
        "/api/v1/projects/",
        json={
            "jira_key": "SEQ",
            "name": "Sequence Project",
            "description": "Project created by sequence test",
            "owner_id": 1,
        },
    )
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()
    assert project["jira_key"] == "SEQ"

    task_response = await client.post(
        "/api/v1/tasks/",
        json={
            "jira_id": "SEQ-1",
            "key": "POH-1",
            "summary": "Sequence Task",
            "description": "Task created by sequence test",
            "task_type": "Story",
            "status": "To Do",
            "priority": "High",
            "project_id": project["id"],
            "estimate_hours": 8,
            "spent_hours": 3,
            "remaining_hours": 5,
            "assignee_name": "Test User",
        },
    )
    assert task_response.status_code == 200, task_response.text
    task = task_response.json()
    assert task["project_id"] == project["id"]

    list_response = await client.get(f"/api/v1/tasks/?project_id={project['id']}")
    assert list_response.status_code == 200, list_response.text
    list_payload = list_response.json()
    assert list_payload["meta"]["total"] == 1
    assert [item["id"] for item in list_payload["data"]] == [task["id"]]

    export_response = await client.post(f"/api/v1/tasks/export?project_id={project['id']}")
    assert export_response.status_code == 202, export_response.text
    export_payload = export_response.json()
    assert export_payload["status"] == "pending"
    task_id = export_payload["task_id"]

    final_status = await _poll_task_status(client, task_id)
    assert final_status["progress"] == 100.0
    assert final_status["result"]["task_count"] == 1
    assert final_status["result"]["project_id"] == project["id"]

    download_response = await client.get(final_status["result"]["download_url"])
    assert download_response.status_code == 200, download_response.text
    assert download_response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert download_response.content[:2] == b"PK"

    workbook = zipfile.ZipFile(BytesIO(download_response.content))
    assert "xl/workbook.xml" in workbook.namelist()
    shared_strings = workbook.read("xl/sharedStrings.xml").decode("utf-8")
    assert "POH-1" in shared_strings
    assert "Sequence Task" in shared_strings
