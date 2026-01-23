"""Analytics utility functions extracted from endpoints for reuse.

This module contains stateless calculation functions used by analytics endpoints:
- Status normalization
- Percentile calculations
- Team health metrics
- DORA metrics
- Sprint burndown calculations
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Status constants
DONE_STATUSES = {"done", "closed", "resolved", "accepted", "completed"}
IN_PROGRESS_STATUSES = {"in progress", "active", "doing"}
FAILURE_STATES = {"failed", "rollback", "reverted"}


def normalize_status(value: Optional[str]) -> str:
    """Normalize status string to lowercase stripped."""
    return (value or "").strip().lower()


def as_float(value: Any) -> float:
    """Safely convert value to float, defaulting to 0.0."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def calculate_percentile(values: List[float], percentile: float) -> Optional[float]:
    """Calculate percentile from list of values using linear interpolation.

    Args:
        values: List of numeric values
        percentile: Percentile to calculate (0.0 to 1.0)

    Returns:
        Calculated percentile value or None if empty list
    """
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * percentile
    lower = math.floor(k)
    upper = math.ceil(k)
    if lower == upper:
        return data[int(k)]
    lower_val = data[int(lower)]
    upper_val = data[int(upper)]
    return lower_val + (upper_val - lower_val) * (k - lower)


async def fetch_sprint_meta(db: AsyncSession, sprint_id: int) -> Optional[Dict[str, Any]]:
    """Fetch sprint metadata for analytics calculations.

    Args:
        db: Database session
        sprint_id: Sprint ID to fetch

    Returns:
        Dictionary with sprint metadata or None if not found
    """
    from app.models import Sprint

    columns = [
        Sprint.__table__.c.id.label("id"),
        Sprint.__table__.c.name.label("name"),
        Sprint.__table__.c.state.label("state"),
        Sprint.__table__.c.project_id.label("project_id"),
        Sprint.__table__.c.start_date.label("start_date"),
        Sprint.__table__.c.end_date.label("end_date"),
        Sprint.__table__.c.complete_date.label("complete_date"),
        Sprint.__table__.c.velocity.label("velocity"),
        Sprint.__table__.c.commitment.label("commitment"),
        Sprint.__table__.c.completed.label("completed"),
    ]
    stmt = select(*columns).where(Sprint.__table__.c.id == sprint_id)
    row = (await db.execute(stmt)).mappings().first()
    return dict(row) if row else None


def compute_team_health(tasks: List[Any]) -> Dict[str, Any]:
    """Compute team health metrics from task list.

    Calculates:
    - Completion rate
    - Blockers and overdue count
    - Estimate vs spent hours
    - Cycle time statistics

    Args:
        tasks: List of Task objects

    Returns:
        Dictionary with team health metrics
    """
    total = len(tasks)
    now = datetime.utcnow()

    done = 0
    in_progress = 0
    blockers = 0
    overdue = 0
    backlog = 0
    estimate_hours = 0.0
    spent_hours = 0.0
    cycle_times: List[float] = []

    for task in tasks:
        status_norm = normalize_status(task.status)
        if status_norm in DONE_STATUSES:
            done += 1
            if task.created_date and task.resolved_date:
                delta = task.resolved_date - task.created_date
                cycle_times.append(delta.total_seconds() / 3600.0)
        elif status_norm in IN_PROGRESS_STATUSES:
            in_progress += 1
        else:
            backlog += 1

        if getattr(task, "is_blocker", False):
            blockers += 1
        if task.due_date and status_norm not in DONE_STATUSES:
            try:
                due = task.due_date
                if isinstance(due, str):
                    due = datetime.fromisoformat(due)
                if due and due < now:
                    overdue += 1
            except Exception:
                pass

        estimate_hours += as_float(task.estimate_hours)
        spent_hours += as_float(task.spent_hours)

    completion_rate = (done / total) if total else 0.0
    avg_cycle = statistics.mean(cycle_times) if cycle_times else None
    median_cycle = statistics.median(cycle_times) if cycle_times else None

    return {
        "total": total,
        "done": done,
        "in_progress": in_progress,
        "backlog": backlog,
        "blockers": blockers,
        "overdue": overdue,
        "completion_rate": round(completion_rate, 4),
        "estimate_hours": round(estimate_hours, 2),
        "spent_hours": round(spent_hours, 2),
        "avg_cycle_time_hours": round(avg_cycle, 2) if avg_cycle is not None else None,
        "median_cycle_time_hours": round(median_cycle, 2) if median_cycle is not None else None,
        "cycle_samples": len(cycle_times),
    }


def calculate_dora_metrics(
    deployments: List[Any],
    incidents: List[Any],
    window_days: int,
) -> Dict[str, Any]:
    """Calculate DORA (DevOps Research and Assessment) metrics.

    Computes:
    - Deployment frequency
    - Lead time for changes
    - Change failure rate
    - Mean time to recovery (MTTR)

    Args:
        deployments: List of deployment/PR objects
        incidents: List of incident objects
        window_days: Time window in days for calculations

    Returns:
        Dictionary with DORA metrics

    Raises:
        ValueError: If window_days is not positive
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    deployment_count = len(deployments)
    lead_times: List[float] = []
    failure_count = 0

    for pr in deployments:
        lead_time = getattr(pr, "lead_time_hours", None)
        if lead_time is None:
            lead_time = getattr(pr, "cycle_time_hours", None)
        if lead_time is not None:
            try:
                lead_times.append(float(lead_time))
            except (TypeError, ValueError):
                pass
        state = (getattr(pr, "state", "") or "").lower().strip()
        rework = getattr(pr, "rework_count", 0) or 0
        if state in FAILURE_STATES or rework > 0:
            failure_count += 1

    deployment_frequency_per_day = deployment_count / window_days if deployment_count else 0.0
    deployment_frequency_per_week = deployment_frequency_per_day * 7

    average_lead = statistics.mean(lead_times) if lead_times else None
    median_lead = statistics.median(lead_times) if lead_times else None
    p90_lead = calculate_percentile(lead_times, 0.9) if lead_times else None

    change_failure_rate = None
    if deployment_count:
        change_failure_rate = failure_count / deployment_count

    mttr_values: List[float] = []
    for incident in incidents:
        opened = getattr(incident, "created_date", None)
        resolved = getattr(incident, "resolved_date", None)
        if opened and resolved and resolved > opened:
            delta = resolved - opened
            mttr_values.append(delta.total_seconds() / 3600.0)

    mttr_avg = statistics.mean(mttr_values) if mttr_values else None
    mttr_median = statistics.median(mttr_values) if mttr_values else None

    return {
        "window_days": window_days,
        "deployments": deployment_count,
        "deployment_frequency_per_day": round(deployment_frequency_per_day, 3)
        if deployment_count
        else 0.0,
        "deployment_frequency_per_week": round(deployment_frequency_per_week, 3)
        if deployment_count
        else 0.0,
        "lead_time_hours": {
            "average": round(average_lead, 2) if average_lead is not None else None,
            "median": round(median_lead, 2) if median_lead is not None else None,
            "p90": round(p90_lead, 2) if p90_lead is not None else None,
            "samples": len(lead_times),
        },
        "change_failure_rate": round(change_failure_rate, 3)
        if change_failure_rate is not None
        else None,
        "mean_time_to_recovery_hours": {
            "average": round(mttr_avg, 2) if mttr_avg is not None else None,
            "median": round(mttr_median, 2) if mttr_median is not None else None,
            "samples": len(mttr_values),
        },
        "totals": {
            "failures": failure_count,
            "incidents": len(incidents),
        },
    }


async def compute_sprint_burndown(db: AsyncSession, sprint_id: int) -> Dict[str, Any]:
    """Compute sprint burndown chart data.

    Calculates ideal vs actual remaining work for each day of the sprint.

    Args:
        db: Database session
        sprint_id: Sprint ID to compute burndown for

    Returns:
        Dictionary with ideal_burndown and actual_burndown arrays
    """
    from app.models import Task

    try:
        sprint = await fetch_sprint_meta(db, sprint_id)
        if not sprint or not sprint.get("start_date") or not sprint.get("end_date"):
            return {"ideal_burndown": [], "actual_burndown": []}

        start: datetime = sprint["start_date"]
        end: datetime = sprint["end_date"]
        total_days = max(1, (end - start).days or 1)

        tasks = (await db.execute(select(Task).where(Task.sprint_id == sprint_id))).scalars().all()
        total_estimate = sum(as_float(t.estimate_hours) for t in tasks)
        if total_estimate <= 0:
            return {"ideal_burndown": [], "actual_burndown": []}

        done_tasks = [
            t
            for t in tasks
            if normalize_status(t.status) in DONE_STATUSES and getattr(t, "resolved_date", None)
        ]

        ideal = []
        actual = []
        for offset in range(total_days + 1):
            day = start + timedelta(days=offset)
            ideal_remaining = total_estimate * (1 - offset / total_days)
            completed = sum(
                as_float(t.estimate_hours)
                for t in done_tasks
                if t.resolved_date and t.resolved_date <= day
            )
            remaining = max(0.0, total_estimate - completed)
            ideal.append({"day": offset, "ideal_remaining": round(ideal_remaining, 2)})
            actual.append({"day": offset, "remaining": round(remaining, 2)})

        return {"ideal_burndown": ideal, "actual_burndown": actual}
    except SQLAlchemyError as exc:
        logger.warning("compute_sprint_burndown(%s) failed: %s", sprint_id, exc)
        return {"ideal_burndown": [], "actual_burndown": [], "error": "db_error"}


__all__ = [
    # Constants
    "DONE_STATUSES",
    "IN_PROGRESS_STATUSES",
    "FAILURE_STATES",
    # Functions
    "normalize_status",
    "as_float",
    "calculate_percentile",
    "fetch_sprint_meta",
    "compute_team_health",
    "calculate_dora_metrics",
    "compute_sprint_burndown",
]
