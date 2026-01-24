import pytest

from app.models import Project
from app.models.traceability import Artifact, ArtifactLink


@pytest.mark.asyncio
async def test_matrix_export_pdf_download_returns_pdf(client, db_session):
    try:
        import reportlab  # noqa: F401
    except Exception:
        pytest.skip("reportlab not installed")

    project = Project(jira_key="PDF", name="PDF Export Project")
    db_session.add(project)
    await db_session.flush()

    row_artifact = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-1",
        display_key="REQ-1",
        title="Requirement 1",
    )
    col_artifact = Artifact(
        project_id=project.id,
        type="test_case",
        source="internal",
        external_id="TC-1",
        display_key="TC-1",
        title="Test Case 1",
    )
    db_session.add_all([row_artifact, col_artifact])
    await db_session.flush()

    db_session.add(
        ArtifactLink(
            project_id=project.id,
            from_artifact_id=row_artifact.id,
            to_artifact_id=col_artifact.id,
            link_type="tests",
            confidence=0.9,
            created_via="manual",
        )
    )
    await db_session.commit()

    payload = {
        "project_id": project.id,
        "format": "pdf",
        "filters": {
            "row_types": ["requirement"],
            "col_types": ["test_case"],
        },
        "include_details": False,
    }
    response = await client.post("/api/v1/traceability/exports", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed"
    task_id = body["task_id"]

    download = await client.get(f"/api/v1/traceability/exports/{task_id}/download")
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")
    assert ".pdf" in download.headers.get("content-disposition", "")
    assert download.content[:4] == b"%PDF"
