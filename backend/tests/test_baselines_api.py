from __future__ import annotations

import pytest

from app.main import app
from app.models.project import Project
from app.models.traceability import Artifact, Baseline, BaselineItem


@pytest.mark.asyncio
async def test_add_baseline_item_requires_exactly_one_target(client, db_session):
    project = Project(jira_key="BLX", name="Baseline XOR", owner_id=1, meta=None)
    db_session.add(project)
    await db_session.flush()

    baseline = Baseline(project_id=project.id, name="BL-1", created_by_id=1)
    db_session.add(baseline)
    await db_session.flush()

    artifact = Artifact(
        project_id=project.id,
        created_by_id=1,
        type="requirement",
        source="manual",
        external_id="REQ-1",
    )
    db_session.add(artifact)
    await db_session.commit()
    await db_session.refresh(baseline)
    await db_session.refresh(artifact)

    response = await client.post(
        f"/api/v1/traceability/baselines/{baseline.id}/items",
        json={
            "baseline_id": baseline.id,
            "artifact_id": artifact.id,
            "link_id": 12345,
        },
    )

    assert response.status_code in {400, 422}


@pytest.mark.asyncio
async def test_export_baseline_csv_returns_attachment_stream(client, db_session):
    project = Project(jira_key="BLC", name="Baseline CSV", owner_id=1, meta=None)
    db_session.add(project)
    await db_session.flush()

    baseline = Baseline(project_id=project.id, name="BL-CSV", created_by_id=1)
    db_session.add(baseline)
    await db_session.flush()

    artifact = Artifact(
        project_id=project.id,
        created_by_id=1,
        type="requirement",
        source="manual",
        external_id="REQ-CSV-1",
    )
    db_session.add(artifact)
    await db_session.flush()

    db_session.add(BaselineItem(baseline_id=baseline.id, artifact_id=artifact.id))
    await db_session.commit()
    await db_session.refresh(baseline)

    response = await client.get(f"/api/v1/traceability/baselines/{baseline.id}/export?format=csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in response.headers["content-disposition"]
    body = response.text
    assert "baseline_id,baseline_name,project_id,item_id,item_type,artifact_id,link_id,included_at" in body
    assert "BL-CSV" in body


@pytest.mark.asyncio
async def test_export_baseline_openapi_contains_csv_variant(client):
    del client
    payload = app.openapi()
    content = payload["paths"]["/api/v1/traceability/baselines/{baseline_id}/export"]["get"]["responses"][
        "200"
    ]["content"]

    assert "application/json" in content
    assert "text/csv" in content


@pytest.mark.asyncio
async def test_export_baseline_csv_does_not_use_bulk_item_loader(
    client, db_session, monkeypatch
):
    project = Project(jira_key="BLS", name="Baseline Stream", owner_id=1, meta=None)
    db_session.add(project)
    await db_session.flush()

    baseline = Baseline(project_id=project.id, name="BL-STREAM", created_by_id=1)
    db_session.add(baseline)
    await db_session.flush()

    artifact = Artifact(
        project_id=project.id,
        created_by_id=1,
        type="requirement",
        source="manual",
        external_id="REQ-STREAM-1",
    )
    db_session.add(artifact)
    await db_session.flush()
    db_session.add(BaselineItem(baseline_id=baseline.id, artifact_id=artifact.id))
    await db_session.commit()
    await db_session.refresh(baseline)

    async def _forbidden_loader(*_args, **_kwargs):
        raise AssertionError("CSV export must not load all items eagerly")

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.traceability.baselines._load_baseline_items",
        _forbidden_loader,
    )

    response = await client.get(f"/api/v1/traceability/baselines/{baseline.id}/export?format=csv")
    assert response.status_code == 200
