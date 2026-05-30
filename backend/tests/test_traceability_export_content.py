"""Content-level matrix export validation (plan_75).

These tests exercise the real renderer (``export_service.process_export_task``)
directly — not just the HTTP status code — asserting CSV/XLSX/PDF output
contains the expected matrix data, plus empty-matrix and unsupported-format
(terminal failure) behavior. Renderers use the already-declared backend
dependencies (openpyxl for xlsx, reportlab for pdf); no new renderer is added.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio

from app.models.project import Project
from app.models.traceability import Artifact, ArtifactLink, ExportTask
from app.services.analytics.export_service import process_export_task


@pytest_asyncio.fixture
async def matrix_project(db_session):
    project = Project(jira_key="EXP", name="Export Project")
    db_session.add(project)
    await db_session.flush()

    req = Artifact(
        project_id=project.id,
        type="requirement",
        source="internal",
        external_id="REQ-1",
        display_key="REQ-1",
        title="Secure login",
    )
    tc = Artifact(
        project_id=project.id,
        type="test_case",
        source="internal",
        external_id="TC-1",
        display_key="TC-1",
        title="Login test",
    )
    db_session.add_all([req, tc])
    await db_session.flush()
    db_session.add(
        ArtifactLink(
            project_id=project.id,
            from_artifact_id=req.id,
            to_artifact_id=tc.id,
            link_type="tests",
            confidence=0.9,
            created_via="manual",
        )
    )
    await db_session.commit()
    return project.id


async def _make_export(db, project_id: int, fmt: str, filters: dict | None = None) -> str:
    task = ExportTask(
        task_id=f"test-{fmt}-{project_id}",
        project_id=project_id,
        export_type="matrix",
        format=fmt,
        status="pending",
        config_json={"filters": filters, "include_details": False},
    )
    db.add(task)
    await db.commit()
    return task.task_id


_DEFAULT_FILTERS = {"row_types": ["requirement"], "col_types": ["test_case"]}


@pytest.mark.asyncio
async def test_csv_export_contains_matrix_data(db_session, matrix_project):
    task_id = await _make_export(db_session, matrix_project, "csv", _DEFAULT_FILTERS)
    result = await process_export_task(db_session, task_id)

    assert result["status"] == "completed"
    path = result["file_path"]
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    # Row key, column key, and coverage summary must all be present.
    assert "REQ-1" in content
    assert "TC-1" in content
    assert "Total Rows" in content


@pytest.mark.asyncio
async def test_xlsx_export_is_valid_workbook(db_session, matrix_project):
    import openpyxl

    task_id = await _make_export(db_session, matrix_project, "xlsx", _DEFAULT_FILTERS)
    result = await process_export_task(db_session, task_id)

    assert result["status"] == "completed"
    path = result["file_path"]
    assert os.path.exists(path)
    wb = openpyxl.load_workbook(path)
    flat = "\n".join(
        str(c.value)
        for ws in wb.worksheets
        for row in ws.iter_rows()
        for c in row
        if c.value is not None
    )
    assert "REQ-1" in flat
    assert result["file_size"] > 0


@pytest.mark.asyncio
async def test_pdf_export_has_pdf_signature(db_session, matrix_project):
    pytest.importorskip("reportlab")
    task_id = await _make_export(db_session, matrix_project, "pdf", _DEFAULT_FILTERS)
    result = await process_export_task(db_session, task_id)

    assert result["status"] == "completed"
    path = result["file_path"]
    with open(path, "rb") as f:
        head = f.read(4)
    assert head == b"%PDF"
    assert result["file_size"] > 0


@pytest.mark.asyncio
async def test_empty_matrix_still_produces_valid_file(db_session, matrix_project):
    # Filter to a row type with no artifacts → empty matrix.
    task_id = await _make_export(
        db_session, matrix_project, "csv", {"row_types": ["nonexistent_type"]}
    )
    result = await process_export_task(db_session, task_id)
    assert result["status"] == "completed"
    assert os.path.exists(result["file_path"])


@pytest.mark.asyncio
async def test_unsupported_format_terminal_failure(db_session, matrix_project):
    task_id = await _make_export(db_session, matrix_project, "docx", _DEFAULT_FILTERS)
    result = await process_export_task(db_session, task_id)
    # Failure must be terminal and carry a readable message.
    assert result["status"] == "failed"
    assert "message" in result and result["message"]


@pytest.mark.asyncio
async def test_include_details_emits_confidence_marker(db_session, matrix_project):
    """include_details=True must surface link type + confidence in the cell."""
    task = ExportTask(
        task_id=f"test-details-{matrix_project}",
        project_id=matrix_project,
        export_type="matrix",
        format="csv",
        status="pending",
        config_json={"filters": _DEFAULT_FILTERS, "include_details": True},
    )
    db_session.add(task)
    await db_session.commit()

    result = await process_export_task(db_session, task.task_id)
    assert result["status"] == "completed"
    with open(result["file_path"], encoding="utf-8") as f:
        content = f.read()
    # Link of type "tests" at confidence 0.9 → cell "tests (90%)".
    assert "tests" in content
    assert "(90%)" in content


@pytest.mark.asyncio
async def test_download_unknown_task_returns_404(client, auth_headers):
    resp = await client.get(
        "/api/v1/traceability/exports/does-not-exist/download", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_not_ready_returns_400(client, db_session, matrix_project, auth_headers):
    task = ExportTask(
        task_id="pending-export-task",
        project_id=matrix_project,
        export_type="matrix",
        format="csv",
        status="pending",
    )
    db_session.add(task)
    await db_session.commit()

    resp = await client.get(
        "/api/v1/traceability/exports/pending-export-task/download", headers=auth_headers
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_uses_bounded_row_col_limits(db_session, matrix_project, monkeypatch):
    """Large-matrix guard: get_rtm_matrix must be called with limits capped by
    MAX_EXPORT_ROWS / MAX_EXPORT_COLS so a huge matrix cannot exhaust memory."""
    import app.services.analytics.export_service as export_service

    captured: dict = {}

    async def _fake_matrix(**kwargs):
        captured.update(kwargs)
        return {"rows": [], "columns": [], "cells": {}, "coverage": {}}

    monkeypatch.setattr(export_service, "get_rtm_matrix", _fake_matrix)

    task_id = await _make_export(db_session, matrix_project, "csv", _DEFAULT_FILTERS)
    await process_export_task(db_session, task_id)

    assert captured["row_limit"] <= export_service.MAX_EXPORT_ROWS
    assert captured["col_limit"] <= export_service.MAX_EXPORT_COLS
