"""Regression coverage for export memory-guard caps and broker-down handling.

Two corner cases that the happy-path export tests don't pin down:

#12 Over-limit caps — ``process_export_task`` must clamp the row/column window
    it requests from ``get_rtm_matrix`` to ``MAX_EXPORT_ROWS`` / ``MAX_EXPORT_COLS``
    via ``min(...)``. This mirrors ``test_export_uses_bounded_row_col_limits`` in
    test_traceability_export_content.py but patches the caps to tiny values so the
    ``min()`` is actually exercised (the default 5000/1000 are below the literal
    10000 ceiling, so a regression to ``min(MAX, 10000)`` -> a bare ``10000`` would
    slip through with the default caps).

#17 Broker-down -> 503 (not 500) — when Celery is enabled but enqueue raises
    (e.g. Redis is down), ``create_export_task`` must persist the task as a
    terminal ``failed`` with a readable message and surface HTTP 503, not leak a
    raw 500 or leave the task stuck in ``pending``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.project import Project
from app.models.traceability import ExportTask


# ---------------------------------------------------------------------------
# #12 Over-limit caps
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def capped_project(db_session):
    project = Project(jira_key="CAP", name="Cap Project")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_export_caps_row_col_limits_to_patched_max(db_session, capped_project, monkeypatch):
    """With MAX_EXPORT_ROWS/COLS patched below the internal 10000 ceiling, the
    limits handed to get_rtm_matrix must be clamped to the (smaller) patched
    caps, proving the min() guard is applied rather than a fixed ceiling."""
    import app.services.analytics.export_service as export_service

    monkeypatch.setattr(export_service, "MAX_EXPORT_ROWS", 3)
    monkeypatch.setattr(export_service, "MAX_EXPORT_COLS", 2)

    captured: dict = {}

    async def _fake_matrix(**kwargs):
        captured.update(kwargs)
        return {"rows": [], "columns": [], "cells": {}, "coverage": {}}

    monkeypatch.setattr(export_service, "get_rtm_matrix", _fake_matrix)

    task = ExportTask(
        task_id=f"cap-export-{capped_project}",
        project_id=capped_project,
        export_type="matrix",
        format="csv",
        status="pending",
        config_json={"filters": None, "include_details": False},
    )
    db_session.add(task)
    await db_session.commit()

    result = await export_service.process_export_task(db_session, task.task_id)

    # The guard must cap regardless: never exceed the patched maximums.
    assert captured["row_limit"] <= export_service.MAX_EXPORT_ROWS
    assert captured["col_limit"] <= export_service.MAX_EXPORT_COLS
    # And with caps below the internal ceiling, min() must pick the small cap
    # exactly (a regression to a hard-coded ceiling would yield 10000 here).
    assert captured["row_limit"] == 3
    assert captured["col_limit"] == 2
    # Sanity: the empty matrix still renders a terminal-success export.
    assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# #17 Broker-down -> 503 (not 500)
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def broker_project(db_session):
    project = Project(jira_key="BRK", name="Broker Project")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_broker_down_returns_503_and_persists_failed(client, broker_project, monkeypatch):
    """Celery enabled + enqueue raising (broker down) must yield HTTP 503 and a
    persisted terminal 'failed' task with a readable error_message — not a 500
    and not a task stuck in 'pending'."""
    import app.api.api_v1.endpoints.traceability.matrix as matrix_module
    import app.tasks.export_tasks as export_tasks

    # Force the Celery enqueue path (conftest defaults CELERY_ENABLED=False).
    previous_celery_enabled = matrix_module.settings.CELERY_ENABLED
    matrix_module.settings.CELERY_ENABLED = True

    def _boom(*args, **kwargs):
        raise RuntimeError("broker down")

    # The endpoint imports export_matrix_task lazily, so patch .delay on the
    # task object the import resolves to.
    monkeypatch.setattr(export_tasks.export_matrix_task, "delay", _boom)

    payload = {
        "project_id": broker_project,
        "format": "csv",
        "filters": {"row_types": ["requirement"], "col_types": ["test_case"]},
        "include_details": False,
    }

    try:
        resp = await client.post("/api/v1/traceability/exports", json=payload)
    finally:
        matrix_module.settings.CELERY_ENABLED = previous_celery_enabled

    # Broker unavailability is a transient/retryable condition -> 503, never 500.
    assert resp.status_code == 503, resp.text

    # The task row must be persisted as a terminal failure with a usable message.
    async with AsyncSessionLocal() as s:
        task = (
            await s.execute(select(ExportTask).where(ExportTask.project_id == broker_project))
        ).scalar_one()
        assert task.status == "failed"
        assert task.error_message
        assert task.error_message.strip()
