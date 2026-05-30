"""Regression tests for bugs found during a code-review hunt.

- #2 export_tasks: a failed export must not clobber ``started_at`` to NULL.
- #3 engine: a dangling edge (referencing a missing node, or an edge without
  source/target) must raise ``ValueError`` (-> HTTP 400), not ``KeyError`` (-> 500).
- #4 task_manager: ``is_cancelled`` must read the persisted CANCELLED status, not
  only the in-memory ``cancellation_token`` (which is per-process and re-created
  unset whenever a task is rehydrated from Redis / after a local-cache eviction).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, SessionLocal
from app.models.traceability import ExportTask
from app.services.rule_execution_engine import RuleExecutionEngine
from app.services.task_manager import TaskManager, TaskStatus


# ---------------------------------------------------------------------------
# #3 engine: dangling edge -> ValueError (not KeyError -> 500)
# ---------------------------------------------------------------------------
def test_topological_sort_rejects_dangling_edge():
    with SessionLocal() as db:
        engine = RuleExecutionEngine(db)
        nodes = [{"id": "node-1", "type": "manualSource", "data": {}}]
        edges = [{"id": "e1", "source": "ghost", "target": "node-1"}]
        with pytest.raises(ValueError):
            engine._topological_sort(nodes, edges)


def test_topological_sort_rejects_edge_missing_source_target():
    with SessionLocal() as db:
        engine = RuleExecutionEngine(db)
        with pytest.raises(ValueError):
            engine._topological_sort([{"id": "a"}], [{"id": "e1"}])


def test_topological_sort_orders_valid_flow():
    with SessionLocal() as db:
        engine = RuleExecutionEngine(db)
        order = engine._topological_sort(
            [{"id": "a"}, {"id": "b"}],
            [{"id": "e1", "source": "a", "target": "b"}],
        )
        assert order.index("a") < order.index("b")


# ---------------------------------------------------------------------------
# #4 task_manager: cancellation observable via persisted status
# ---------------------------------------------------------------------------
def test_is_cancelled_reads_persisted_cancelled_status():
    """A task rehydrated from Redis (or after a cache eviction) comes back with a
    fresh, unset ``cancellation_token``; the CANCELLED status is what persists, so
    ``is_cancelled`` must honour it. Before the fix this returned False (the lost
    token), so ``cancel_task`` reported success but the task never stopped."""
    tm = TaskManager()
    task_id = tm.create_task("t")

    task = tm.get_task(task_id)
    task.status = TaskStatus.CANCELLED
    task.cancellation_token = asyncio.Event()  # fresh, unset (mimics rehydration)
    tm._tasks[task_id] = task

    assert tm.is_cancelled(task_id) is True


# ---------------------------------------------------------------------------
# #2 export: a failed export keeps its real started_at
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_export_preserves_started_at(db_session):
    from app.tasks.export_tasks import _update_export_status

    started = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    db_session.add(
        ExportTask(
            task_id="exp-fail-1",
            export_type="matrix",
            format="csv",
            status="processing",
            started_at=started,
        )
    )
    await db_session.commit()

    # The only failure-path caller passes status="failed".
    await _update_export_status("exp-fail-1", "failed", "boom")

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(ExportTask).where(ExportTask.task_id == "exp-fail-1"))
        ).scalar_one()
    assert row.status == "failed"
    assert row.error_message == "boom"
    # The real start time must survive (was being clobbered to NULL).
    assert row.started_at is not None


@pytest.mark.asyncio
async def test_processing_export_stamps_started_at(db_session):
    """Positive counterpart: transitioning to 'processing' DOES set started_at."""
    from app.tasks.export_tasks import _update_export_status

    db_session.add(
        ExportTask(task_id="exp-proc-1", export_type="matrix", format="csv", status="pending")
    )
    await db_session.commit()

    await _update_export_status("exp-proc-1", "processing")

    async with AsyncSessionLocal() as s:
        row = (
            await s.execute(select(ExportTask).where(ExportTask.task_id == "exp-proc-1"))
        ).scalar_one()
    assert row.status == "processing"
    assert row.started_at is not None
