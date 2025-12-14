from __future__ import annotations

import logging

from collections import defaultdict
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, desc, func, or_, select
import math
import statistics
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import CoverageReport, Project, PullRequest, Sprint, Task, TestResult


router = APIRouter()

logger = logging.getLogger(__name__)

DONE_STATUSES = {"done", "closed", "resolved", "accepted", "completed"}


def _normalize_status(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


async def _fetch_sprint_meta(db: AsyncSession, sprint_id: int) -> Optional[Dict[str, Any]]:
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



def _percentile(values: List[float], percentile: float) -> float | None:
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


FAILURE_STATES = {"failed", "rollback", "reverted"}

def _compute_team_health(tasks: List[Task]) -> Dict[str, Any]:
    total = len(tasks)
    done_statuses = {"done", "closed", "resolved", "complete"}
    in_progress_statuses = {"in progress", "active", "doing"}

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
        status_norm = _normalize_status(task.status)
        if status_norm in done_statuses:
            done += 1
            if task.created_date and task.resolved_date:
                delta = task.resolved_date - task.created_date
                cycle_times.append(delta.total_seconds() / 3600.0)
        elif status_norm in in_progress_statuses:
            in_progress += 1
        else:
            backlog += 1

        if getattr(task, "is_blocker", False):
            blockers += 1
        if task.due_date and status_norm not in done_statuses:
            try:
                due = task.due_date
                if isinstance(due, str):
                    due = datetime.fromisoformat(due)
                if due and due < now:
                    overdue += 1
            except Exception:
                pass

        estimate_hours += _as_float(task.estimate_hours)
        spent_hours += _as_float(task.spent_hours)

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



def _calculate_dora_metrics(
    deployments: List[Any], incidents: List[Any], window_days: int
) -> Dict[str, Any]:
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
    p90_lead = _percentile(lead_times, 0.9) if lead_times else None

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
        "deployment_frequency_per_day": round(deployment_frequency_per_day, 3) if deployment_count else 0.0,
        "deployment_frequency_per_week": round(deployment_frequency_per_week, 3) if deployment_count else 0.0,
        "lead_time_hours": {
            "average": round(average_lead, 2) if average_lead is not None else None,
            "median": round(median_lead, 2) if median_lead is not None else None,
            "p90": round(p90_lead, 2) if p90_lead is not None else None,
            "samples": len(lead_times),
        },
        "change_failure_rate": round(change_failure_rate, 3) if change_failure_rate is not None else None,
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



async def _compute_sprint_burndown(db: AsyncSession, sprint_id: int) -> Dict[str, Any]:
    try:
        sprint = await _fetch_sprint_meta(db, sprint_id)
        if not sprint or not sprint.get("start_date") or not sprint.get("end_date"):
            return {"ideal_burndown": [], "actual_burndown": []}

        start: datetime = sprint["start_date"]
        end: datetime = sprint["end_date"]
        total_days = max(1, (end - start).days or 1)

        tasks = (
            await db.execute(select(Task).where(Task.sprint_id == sprint_id))
        ).scalars().all()
        total_estimate = sum(_as_float(t.estimate_hours) for t in tasks)
        if total_estimate <= 0:
            return {"ideal_burndown": [], "actual_burndown": []}

        done_tasks = [
            t
            for t in tasks
            if _normalize_status(t.status) in DONE_STATUSES and getattr(t, "resolved_date", None)
        ]

        ideal = []
        actual = []
        for offset in range(total_days + 1):
            day = start + timedelta(days=offset)
            ideal_remaining = total_estimate * (1 - offset / total_days)
            completed = sum(
                _as_float(t.estimate_hours)
                for t in done_tasks
                if t.resolved_date and t.resolved_date <= day
            )
            remaining = max(0.0, total_estimate - completed)
            ideal.append({"day": offset, "ideal_remaining": round(ideal_remaining, 2)})
            actual.append({"day": offset, "remaining": round(remaining, 2)})

        return {"ideal_burndown": ideal, "actual_burndown": actual}
    except SQLAlchemyError as exc:
        logger.warning("_compute_sprint_burndown(%s) failed: %s", sprint_id, exc)
        return {"ideal_burndown": [], "actual_burndown": [], "error": "db_error"}


@router.get("/projects/{project_id}/velocity")
async def get_project_velocity(
    project_id: int,
    sprints_count: int = 5,
    db: AsyncSession = Depends(get_db),
):
    start = perf_counter()
    logger.info("analytics.project_velocity.start project_id=%s sprints_count=%s", project_id, sprints_count)
    try:
        limit = max(1, int(sprints_count or 5))
        stmt = (
            select(
                Sprint.__table__.c.id.label("id"),
                Sprint.__table__.c.name.label("name"),
                Sprint.__table__.c.end_date.label("end_date"),
            )
            .where(Sprint.__table__.c.project_id == project_id)
            .where(Sprint.__table__.c.state == "closed")
            .order_by(Sprint.__table__.c.end_date.desc())
            .limit(limit)
        )
        sprint_rows = (await db.execute(stmt)).mappings().all()
        if not sprint_rows:
            duration = perf_counter() - start
            logger.info("analytics.project_velocity.empty project_id=%s duration=%.3f", project_id, duration)
            return {
                "average_velocity": 0.0,
                "sprints_analyzed": 0,
                "velocity_trend": "insufficient_data",
                "sprint_velocities": [],
            }

        # OPTIMIZED: Single query with GROUP BY instead of N+1 queries
        # Get sprint IDs for the velocity calculation
        sprint_ids = [row["id"] for row in sprint_rows]

        done_statuses = list(DONE_STATUSES)

        # Single query to get velocities for all sprints at once
        velocity_stmt = (
            select(
                Task.sprint_id,
                func.sum(Task.estimate_hours).label("completed_hours")
            )
            .where(Task.sprint_id.in_(sprint_ids))
            .where(func.lower(Task.status).in_(done_statuses))
            .group_by(Task.sprint_id)
        )
        velocity_rows = (await db.execute(velocity_stmt)).mappings().all()

        # Create a lookup dict for O(1) access
        velocity_by_sprint = {
            row["sprint_id"]: _as_float(row["completed_hours"])
            for row in velocity_rows
        }

        # Build velocities list with data from single query
        velocities: List[Dict[str, Any]] = []
        for row in sprint_rows:
            completed = velocity_by_sprint.get(row["id"], 0.0)
            velocities.append(
                {
                    "sprint_id": row["id"],
                    "sprint_name": row["name"],
                    "velocity": round(completed, 2),
                    "end_date": row["end_date"],
                }
            )

        avg_velocity = sum(v["velocity"] for v in velocities) / max(1, len(velocities))
        trend = "insufficient_data"
        if len(velocities) >= 4:
            recent = sum(v["velocity"] for v in velocities[:2]) / 2
            older = sum(v["velocity"] for v in velocities[2:4]) / 2
            if recent > older * 1.1:
                trend = "increasing"
            elif recent < older * 0.9:
                trend = "decreasing"
            else:
                trend = "stable"

        response = {
            "average_velocity": round(avg_velocity, 2),
            "sprints_analyzed": len(velocities),
            "velocity_trend": trend,
            "sprint_velocities": velocities,
        }
        duration = perf_counter() - start
        logger.info("analytics.project_velocity.success project_id=%s sprints=%s avg=%.2f duration=%.3f", project_id, len(velocities), response["average_velocity"], duration)
        return response
    except Exception:
        logger.exception("analytics.project_velocity.error project_id=%s duration=%.3f", project_id, perf_counter() - start)
        raise



@router.get("/projects/{project_id}/dora")
async def get_dora_metrics(
    project_id: int,
    window_days: int = 30,
    db: AsyncSession = Depends(get_db),
):
    window_days = max(1, int(window_days or 30))
    since = datetime.utcnow() - timedelta(days=window_days)
    now_utc = datetime.utcnow()

    logger.info("analytics.dora.start project_id=%s window=%s", project_id, window_days)

    # Get task keys for the project
    task_key_rows = await db.execute(select(Task.key).where(Task.project_id == project_id))
    task_keys = {str(row[0]).upper() for row in task_key_rows.all() if row[0]}
    if not task_keys:
        logger.info("analytics.dora.no_tasks project_id=%s", project_id)
        metrics = _calculate_dora_metrics([], [], window_days)
        metrics["timeframe"] = {"start": since.isoformat(), "end": now_utc.isoformat()}
        return metrics

    # OPTIMIZED: Filter PRs by repository_id to reduce the dataset before Python filtering
    # Get repository IDs associated with this project
    from app.models import ProjectRepository
    repo_ids_stmt = select(ProjectRepository.repository_id).where(ProjectRepository.project_id == project_id)
    repo_ids_rows = (await db.execute(repo_ids_stmt)).scalars().all()
    repo_ids = list(repo_ids_rows)

    if repo_ids:
        # Filter PRs by repository_id AND merged_at to significantly reduce dataset
        pr_stmt = (
            select(PullRequest)
            .where(PullRequest.repository_id.in_(repo_ids))
            .where(PullRequest.merged_at.is_not(None))
            .where(PullRequest.merged_at >= since)
        )
    else:
        # Fallback to original query if no repositories found
        pr_stmt = (
            select(PullRequest)
            .where(PullRequest.merged_at.is_not(None))
            .where(PullRequest.merged_at >= since)
        )

    # Still need to filter by jira_keys overlap in Python (could be optimized further with JSONB operators)
    deployments = []
    for pr in (await db.execute(pr_stmt)).scalars().all():
        keys = {str(key).upper() for key in (pr.jira_keys or []) if isinstance(key, str)}
        if keys and keys & task_keys:
            deployments.append(pr)

    incident_stmt = (
        select(Task)
        .where(Task.project_id == project_id)
        .where(Task.task_type.is_not(None))
        .where(func.lower(Task.task_type).like('%incident%'))
        .where(or_(Task.created_date >= since, Task.resolved_date >= since))
    )
    incidents = (await db.execute(incident_stmt)).scalars().all()

    metrics = _calculate_dora_metrics(deployments, incidents, window_days)
    metrics["timeframe"] = {"start": since.isoformat(), "end": now_utc.isoformat()}
    metrics["totals"].update({"deployments_considered": len(deployments)})
    logger.info(
        "analytics.dora.success project_id=%s deployments=%s incidents=%s",
        project_id,
        len(deployments),
        len(incidents),
    )
    return metrics



@router.get("/projects/{project_id}/budget-hours")
async def project_budget_hours(
    project_id: int,
    top_n: int = 5,
    db: AsyncSession = Depends(get_db),
):
    start = perf_counter()
    logger.info("analytics.budget_hours.start project_id=%s top_n=%s", project_id, top_n)

    # Try to get from cache first
    try:
        from app.services.cache_service import cache_service
        cache_key = cache_service._make_key("budget_hours", project_id, top_n)
    except ImportError:
        cache_service = None
        cache_key = None
    if cache_service and cache_key:
        cached_result = cache_service.get(cache_key)
        if cached_result:
            logger.info("analytics.budget_hours.cache_hit project_id=%s", project_id)
            return cached_result

    try:
        # Prepare queries
        totals_stmt = (
            select(
                func.coalesce(func.sum(Task.estimate_hours), 0).label("estimate"),
                func.coalesce(func.sum(Task.spent_hours), 0).label("spent"),
            )
            .where(Task.project_id == project_id)
        )

        diff = Task.spent_hours - Task.estimate_hours
        over_stmt = (
            select(Task.key, diff.label("delta"))
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_not(None))
            .where(Task.spent_hours.is_not(None))
            .where(diff > 0)
            .order_by(desc(diff))
            .limit(max(1, min(int(top_n or 5), 50)))
        )

        # Execute queries sequentially
        try:
            totals_result = await db.execute(totals_stmt)
            over_result = await db.execute(over_stmt)

            totals = totals_result.first()
            total_estimate = _as_float(totals.estimate if totals else 0)
            total_spent = _as_float(totals.spent if totals else 0)
            remaining = max(0.0, total_estimate - total_spent)
            overrun_hours = max(0.0, total_spent - total_estimate)

            top_overruns = [
                {"key": key, "overrun_hours": round(_as_float(delta), 2)}
                for key, delta in over_result.all()
            ]

            response = {
                "total_estimate_hours": round(total_estimate, 2),
                "total_spent_hours": round(total_spent, 2),
                "remaining_hours": round(remaining, 2),
                "overrun": total_spent > total_estimate,
                "overrun_hours": round(overrun_hours, 2),
                "top_overruns": top_overruns,
            }

            # Cache the result
            if cache_service and cache_key:
                cache_service.set(cache_key, response, ttl=120)  # Cache for 2 minutes

            logger.info("analytics.budget_hours.success project_id=%s overrun=%s duration=%.3f",
                       project_id, response['overrun'], perf_counter() - start)
            return response

        except Exception as e:
            logger.error("analytics.budget_hours.query_error project_id=%s duration=%.3f error=%s",
                        project_id, perf_counter() - start, str(e))
            return {
                "total_estimate_hours": 0.0,
                "total_spent_hours": 0.0,
                "remaining_hours": 0.0,
                "overrun": False,
                "overrun_hours": 0.0,
                "top_overruns": [],
                "error": "query_error",
            }

    except Exception:
        logger.exception("analytics.budget_hours.error project_id=%s duration=%.3f",
                        project_id, perf_counter() - start)
        return {
            "total_estimate_hours": 0.0,
            "total_spent_hours": 0.0,
            "remaining_hours": 0.0,
            "overrun": False,
            "overrun_hours": 0.0,
            "top_overruns": [],
            "error": "db_error",
        }


@router.get("/projects/{project_id}/value-metrics")
async def project_value_metrics(project_id: int, db: AsyncSession = Depends(get_db)):
    start = perf_counter()
    logger.info("analytics.value_metrics.start project_id=%s", project_id)

    # Try to get from cache first
    try:
        from app.services.cache_service import cache_service
        cache_key = cache_service._make_key("value_metrics", project_id)
    except ImportError:
        cache_service = None
        cache_key = None

    if cache_service and cache_key:
        cached_result = cache_service.get(cache_key)
        if cached_result:
            logger.info("analytics.value_metrics.cache_hit project_id=%s", project_id)
            return cached_result

    try:
        import asyncio

        # Optimized query with coalesce for NULL handling
        value_case = case((Task.value_delivered == True, Task.business_value), else_=0.0)  # noqa: E712
        stmt = (
            select(
                func.coalesce(func.sum(Task.business_value), 0).label("total_value"),
                func.coalesce(func.sum(value_case), 0).label("value_delivered"),
                func.coalesce(func.sum(Task.spent_hours), 0).label("spent"),
            )
            .where(Task.project_id == project_id)
        )

        # Execute with timeout
        try:
            row = await asyncio.wait_for(
                db.execute(stmt),
                timeout=10.0  # 10 second timeout
            )
            row = row.first()

            total_value = _as_float(row.total_value if row else 0)
            delivered = _as_float(row.value_delivered if row else 0)
            spent = _as_float(row.spent if row else 0)
            roi = delivered / spent if spent else 0.0

            response = {
                "value_delivered": round(delivered, 2),
                "total_spent_hours": round(spent, 2),
                "roi": round(roi, 2),
                "total_value": round(total_value, 2),
            }

            # Cache the result
            if cache_service and cache_key:
                cache_service.set(cache_key, response, ttl=120)  # Cache for 2 minutes

            logger.info("analytics.value_metrics.success project_id=%s roi=%.2f duration=%.3f",
                       project_id, response['roi'], perf_counter() - start)
            return response

        except asyncio.TimeoutError:
            logger.error("analytics.value_metrics.timeout project_id=%s duration=%.3f",
                        project_id, perf_counter() - start)
            return {
                "value_delivered": 0.0,
                "total_spent_hours": 0.0,
                "roi": 0.0,
                "total_value": 0.0,
                "error": "timeout",
            }

    except Exception:
        logger.exception("analytics.value_metrics.error project_id=%s duration=%.3f",
                        project_id, perf_counter() - start)
        return {
            "value_delivered": 0.0,
            "total_spent_hours": 0.0,
            "roi": 0.0,
            "total_value": 0.0,
            "error": "db_error",
        }


@router.get("/sprints/{sprint_id}/wip-status")
async def sprint_wip_status(sprint_id: int, db: AsyncSession = Depends(get_db)):
    start = perf_counter()
    logger.info("analytics.sprint_wip.start sprint_id=%s", sprint_id)
    try:
        # OPTIMIZED: Use GROUP BY query instead of loading all tasks and filtering in Python
        done_statuses = list(DONE_STATUSES)

        # Query to count active tasks grouped by assignee
        # Use COALESCE to handle assignee_email OR assignee_name OR 'unassigned'
        aggregates_stmt = (
            select(
                func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned").label("assignee"),
                func.count(Task.id).label("active_count")
            )
            .where(Task.sprint_id == sprint_id)
            .where(func.lower(Task.status).notin_(done_statuses))
            .group_by(func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned"))
        )

        aggregates_rows = (await db.execute(aggregates_stmt)).mappings().all()

        # Also get total active count for response
        total_active = sum(row["active_count"] for row in aggregates_rows)

        from app.core.config import settings as _settings  # local import to avoid cycles

        limit_default = getattr(_settings, "WIP_LIMIT_PER_ASSIGNEE", 2) or 2
        overrides = getattr(_settings, "WIP_LIMIT_OVERRIDES", {}) or {}

        def eff_limit(assignee: str) -> int:
            override = overrides.get(assignee) or overrides.get((assignee or "").lower())
            try:
                if override is not None:
                    return int(override)
            except Exception:
                pass
            return limit_default

        # Build assignees list from aggregated data
        assignees = []
        for row in sorted(aggregates_rows, key=lambda r: (-r["active_count"], r["assignee"])):
            name = row["assignee"]
            count = row["active_count"]
            limit = eff_limit(name)
            assignees.append(
                {
                    "assignee": name,
                    "active_tasks": count,
                    "limit": limit,
                    "wip_exceeded": bool(count > limit),
                }
            )

        logger.info(
            "analytics.sprint_wip.success sprint_id=%s active=%s duration=%.3f",
            sprint_id,
            total_active,
            perf_counter() - start,
        )
        return {
            "total_active": total_active,
            "limit_default": limit_default,
            "assignees": assignees,
        }
    except SQLAlchemyError as exc:
        logger.warning(
            "analytics.sprint_wip.error sprint_id=%s duration=%.3f error=%s",
            sprint_id,
            perf_counter() - start,
            exc,
        )
        return {"total_active": 0, "limit_default": 2, "assignees": [], "error": "db_error"}


@router.get("/sprints/{sprint_id}/capacity")
async def sprint_capacity(sprint_id: int, db: AsyncSession = Depends(get_db)):
    try:
        sprint = await _fetch_sprint_meta(db, sprint_id)
        if not sprint:
            return {
                "sprint_id": sprint_id,
                "weeks": 1,
                "capacity_hours_per_person": 40.0,
                "total_planned_hours": 0.0,
                "assignees": [],
            }

        # OPTIMIZED: Use GROUP BY query instead of loading all tasks and summing in Python
        planned_stmt = (
            select(
                func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned").label("assignee"),
                func.coalesce(func.sum(Task.estimate_hours), 0.0).label("planned_hours")
            )
            .where(Task.sprint_id == sprint_id)
            .group_by(func.coalesce(Task.assignee_email, Task.assignee_name, "unassigned"))
        )

        planned_rows = (await db.execute(planned_stmt)).mappings().all()

        start = sprint.get("start_date")
        end = sprint.get("end_date")
        duration_days = max(1, ((end or start) - start).days) if (start and end) else 7
        weeks = max(1.0, round(duration_days / 7.0, 2))
        capacity_per_person = round(40.0 * weeks, 2)

        # Build assignees list from aggregated data
        assignees = []
        total_planned = 0.0
        for row in sorted(planned_rows, key=lambda r: r["assignee"]):
            name = row["assignee"]
            hours = _as_float(row["planned_hours"])
            total_planned += hours
            utilization = (hours / capacity_per_person * 100.0) if capacity_per_person else 0.0
            assignees.append(
                {
                    "assignee": name,
                    "planned_hours": round(hours, 2),
                    "capacity_hours": capacity_per_person,
                    "utilization_pct": round(utilization, 2),
                }
            )

        return {
            "sprint_id": sprint_id,
            "weeks": weeks,
            "capacity_hours_per_person": capacity_per_person,
            "total_planned_hours": round(total_planned, 2),
            "assignees": assignees,
        }
    except SQLAlchemyError as exc:
        logger.warning("sprint_capacity(%s) failed: %s", sprint_id, exc)
        return {"sprint_id": sprint_id, "weeks": 1, "capacity_hours_per_person": 40.0, "total_planned_hours": 0.0, "assignees": [], "error": "db_error"}


@router.get("/projects/{project_id}/sprints")
async def project_sprints(
    project_id: int,
    limit: int = Query(10, ge=1, le=100),
    board_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    start = perf_counter()
    logger.info("analytics.project_sprints.start project_id=%s limit=%s board_id=%s", project_id, limit, board_id)

    # Try to get from cache first
    from app.services.cache_service import cache_service
    cache_key = cache_service._make_key("project_sprints", project_id, limit, board_id)
    cached_result = cache_service.get(cache_key)
    if cached_result:
        logger.info("analytics.project_sprints.cache_hit project_id=%s", project_id)
        return cached_result

    try:
        # Use optimized query with only necessary columns
        stmt = (
            select(
                Sprint.id.label("sprint_id"),
                Sprint.name,
                Sprint.state,
                Sprint.goal,
                Sprint.start_date,
                Sprint.end_date,
                Sprint.complete_date,
                Sprint.velocity,
                Sprint.commitment,
                Sprint.completed,
            )
            .where(Sprint.project_id == project_id)
            .order_by(Sprint.start_date.desc().nullslast())  # Handle nulls properly
            .limit(limit)
        )

        # Execute with timeout context - increased timeout to handle slow queries
        import asyncio
        try:
            rows = await asyncio.wait_for(
                db.execute(stmt),
                timeout=30.0  # Increased to 30 seconds to avoid timeout errors
            )
            sprints = []
            for row in rows.mappings():
                sprint = dict(row)
                sprint["id"] = sprint.get("sprint_id")
                sprints.append(sprint)

            result = {
                "total": len(sprints),
                "board_id": board_id,
                "sprints": sprints
            }

            # Cache the result for longer to avoid repeated slow queries
            cache_service.set(cache_key, result, ttl=300)  # Cache for 5 minutes

            logger.info(
                "analytics.project_sprints.success project_id=%s count=%s duration=%.3f",
                project_id,
                len(sprints),
                perf_counter() - start,
            )
            return result

        except asyncio.TimeoutError:
            logger.error(
                "analytics.project_sprints.timeout project_id=%s duration=%.3f",
                project_id,
                perf_counter() - start,
            )
            # Return empty result with longer cache to avoid repeated timeouts
            empty_result = {"total": 0, "board_id": board_id, "sprints": [], "error": "timeout"}
            cache_service.set(cache_key, empty_result, ttl=60)  # Cache empty result for 1 minute
            return empty_result

    except SQLAlchemyError as exc:
        logger.warning(
            "analytics.project_sprints.error project_id=%s duration=%.3f error=%s",
            project_id,
            perf_counter() - start,
            exc,
        )
        return {"total": 0, "board_id": board_id, "sprints": [], "error": "db_error"}


@router.get("/sprints/{sprint_id}/burndown")
async def sprint_burndown(sprint_id: int, db: AsyncSession = Depends(get_db)):
    try:
        data = await _compute_sprint_burndown(db, sprint_id)
        return data
    except SQLAlchemyError as exc:
        logger.warning("sprint_burndown(%s) failed: %s", sprint_id, exc)
        return {"ideal_burndown": [], "actual_burndown": [], "error": "db_error"}


@router.get("/sprints/{sprint_id}/quality")
async def sprint_quality(sprint_id: int, db: AsyncSession = Depends(get_db)):
    try:
        # OPTIMIZED: Use aggregate queries with CASE statements instead of loading all tasks
        done_statuses = list(DONE_STATUSES)

        # Query to get counts in a single query
        counts_stmt = (
            select(
                func.count(Task.id).label("total"),
                func.sum(case((func.lower(Task.status).in_(done_statuses), 1), else_=0)).label("done"),
                func.sum(case((Task.is_blocker == True, 1), else_=0)).label("blockers")
            )
            .where(Task.sprint_id == sprint_id)
        )
        counts = (await db.execute(counts_stmt)).mappings().first()

        total = counts["total"] or 0
        done = counts["done"] or 0
        blockers = counts["blockers"] or 0

        # Query to get bugs grouped by priority
        bugs_stmt = (
            select(
                func.coalesce(Task.priority, "Unspecified").label("priority"),
                func.count(Task.id).label("bug_count")
            )
            .where(Task.sprint_id == sprint_id)
            .where(func.lower(Task.task_type) == "bug")
            .group_by(func.coalesce(Task.priority, "Unspecified"))
        )
        bugs_rows = (await db.execute(bugs_stmt)).mappings().all()
        bugs = {row["priority"]: row["bug_count"] for row in bugs_rows}

        dod_pct = (done / total * 100.0) if total else 0.0
        return {
            "total_tasks": total,
            "dod_pct": round(dod_pct, 2),
            "bugs_by_priority": bugs,
            "blockers": blockers,
        }
    except SQLAlchemyError as exc:
        logger.warning("sprint_quality(%s) failed: %s", sprint_id, exc)
        return {"total_tasks": 0, "dod_pct": 0.0, "bugs_by_priority": {}, "blockers": 0, "error": "db_error"}




@router.get("/projects/{project_id}/team-members")
async def get_team_members_activity(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get team members with their last activity dates"""
    try:
        # OPTIMIZED: Use GROUP BY query with CASE statements instead of loading all tasks
        done_statuses_set = {"done", "closed", "resolved", "complete"}
        active_statuses_set = {"in progress", "active", "doing"}

        # Single query to aggregate all stats by assignee
        team_stmt = (
            select(
                Task.assignee_name.label("name"),
                Task.assignee_email.label("email"),
                func.count(Task.id).label("total_tasks"),
                func.sum(
                    case(
                        (func.lower(Task.status).in_(list(done_statuses_set)), 1),
                        else_=0
                    )
                ).label("completed_tasks"),
                func.sum(
                    case(
                        (func.lower(Task.status).in_(list(active_statuses_set)), 1),
                        else_=0
                    )
                ).label("active_tasks"),
                func.max(Task.updated_date).label("last_activity")
            )
            .where(Task.project_id == project_id)
            .where(
                or_(
                    Task.assignee_email.is_not(None),
                    Task.assignee_name.is_not(None)
                )
            )
            .group_by(Task.assignee_email, Task.assignee_name)
        )

        team_rows = (await db.execute(team_stmt)).mappings().all()

        # Convert to list and add days_since_activity
        now = datetime.now()  # Use local time instead of UTC to match database timestamps
        result = []
        for row in team_rows:
            member = {
                "name": row["name"],
                "email": row["email"],
                "total_tasks": row["total_tasks"],
                "active_tasks": row["active_tasks"] or 0,
                "completed_tasks": row["completed_tasks"] or 0,
                "last_activity": None,
                "days_since_activity": None,
            }

            if row["last_activity"]:
                # Make sure last_activity is timezone-naive for comparison
                last_act = row["last_activity"]
                if hasattr(last_act, 'tzinfo') and last_act.tzinfo is not None:
                    last_act = last_act.replace(tzinfo=None)

                delta = now - last_act
                # Calculate days, handling negative deltas (future dates due to timezone issues)
                days = delta.days
                # If delta is negative but total_seconds is less than 24 hours, treat as today
                if days < 0 and abs(delta.total_seconds()) < 86400:
                    days = 0
                member["days_since_activity"] = max(0, days)
                member["last_activity"] = row["last_activity"].isoformat()

            result.append(member)

        # Sort by last activity (most recent first)
        result.sort(key=lambda x: x["last_activity"] or "", reverse=True)

        return result

    except SQLAlchemyError as exc:
        logger.warning("get_team_members_activity error: %s", exc)
        return []


@router.get("/projects/{project_id}/team-health")
async def get_project_team_health(project_id: int, db: AsyncSession = Depends(get_db)):
    try:
        # OPTIMIZED: Use aggregate queries instead of loading all tasks and computing in Python
        done_statuses_set = {"done", "closed", "resolved", "complete"}
        in_progress_statuses_set = {"in progress", "active", "doing"}
        now = datetime.utcnow()

        # Main aggregation query
        counts_stmt = (
            select(
                func.count(Task.id).label("total"),
                func.sum(case((func.lower(Task.status).in_(list(done_statuses_set)), 1), else_=0)).label("done"),
                func.sum(case((func.lower(Task.status).in_(list(in_progress_statuses_set)), 1), else_=0)).label("in_progress"),
                func.sum(case((Task.is_blocker == True, 1), else_=0)).label("blockers"),
                func.sum(
                    case(
                        (
                            and_(
                                Task.due_date.is_not(None),
                                Task.due_date < now,
                                func.lower(Task.status).notin_(list(done_statuses_set))
                            ),
                            1
                        ),
                        else_=0
                    )
                ).label("overdue"),
                func.coalesce(func.sum(Task.estimate_hours), 0.0).label("estimate_hours"),
                func.coalesce(func.sum(Task.spent_hours), 0.0).label("spent_hours")
            )
            .where(Task.project_id == project_id)
        )
        counts = (await db.execute(counts_stmt)).mappings().first()

        total = counts["total"] or 0
        if total == 0:
            return {
                "total": 0,
                "done": 0,
                "in_progress": 0,
                "backlog": 0,
                "blockers": 0,
                "overdue": 0,
                "completion_rate": 0.0,
                "estimate_hours": 0.0,
                "spent_hours": 0.0,
                "avg_cycle_time_hours": None,
                "median_cycle_time_hours": None,
                "cycle_samples": 0,
            }

        done = counts["done"] or 0
        in_progress = counts["in_progress"] or 0
        backlog = total - done - in_progress
        blockers = counts["blockers"] or 0
        overdue = counts["overdue"] or 0
        estimate_hours = _as_float(counts["estimate_hours"])
        spent_hours = _as_float(counts["spent_hours"])

        # Calculate cycle times for done tasks
        cycle_stmt = (
            select(
                func.extract('epoch', Task.resolved_date - Task.created_date).label("cycle_seconds")
            )
            .where(Task.project_id == project_id)
            .where(func.lower(Task.status).in_(list(done_statuses_set)))
            .where(Task.created_date.is_not(None))
            .where(Task.resolved_date.is_not(None))
        )
        cycle_rows = (await db.execute(cycle_stmt)).scalars().all()
        cycle_times = [float(seconds) / 3600.0 for seconds in cycle_rows if seconds is not None]

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
    except SQLAlchemyError as exc:
        logger.warning("analytics.team_health.error project_id=%s error=%s", project_id, exc)
        return {
            "total": 0,
            "done": 0,
            "in_progress": 0,
            "backlog": 0,
            "blockers": 0,
            "overdue": 0,
            "completion_rate": 0.0,
            "estimate_hours": 0.0,
            "spent_hours": 0.0,
            "avg_cycle_time_hours": None,
            "median_cycle_time_hours": None,
            "cycle_samples": 0,
            "error": "db_error",
        }

@router.get("/projects/{project_id}/burndown")
async def project_burndown(
    project_id: int,
    sprint_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    try:
        target_id = sprint_id
        sprint_meta: Optional[Dict[str, Any]] = None

        if target_id is None:
            priority = case(
                (Sprint.__table__.c.state == "active", 0),
                (Sprint.__table__.c.state == "future", 1),
                else_=2,
            )
            stmt = (
                select(Sprint.__table__.c.id)
                .where(Sprint.__table__.c.project_id == project_id)
                .order_by(priority, Sprint.__table__.c.start_date.desc())
                .limit(1)
            )
            row = (await db.execute(stmt)).first()
            target_id = row.id if row else None

        if not target_id:
            return {"sprint": None, "ideal_burndown": [], "actual_burndown": []}

        sprint_meta = await _fetch_sprint_meta(db, target_id)
        data = await _compute_sprint_burndown(db, target_id)
        data["sprint"] = sprint_meta
        return data
    except SQLAlchemyError as exc:
        logger.warning("project_burndown(%s) failed: %s", project_id, exc)
        return {"sprint": None, "ideal_burndown": [], "actual_burndown": [], "error": "db_error"}


@router.get("/projects/{project_id}/risks")
async def identify_project_risks(project_id: int, db: AsyncSession = Depends(get_db)):
    try:
        # OPTIMIZED: Use targeted queries for each risk type instead of loading all tasks
        now = datetime.utcnow()
        done_statuses = list(DONE_STATUSES)
        risks: List[Dict[str, Any]] = []

        # Risk 1: Overdue tasks
        overdue_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.due_date.is_not(None))
            .where(Task.due_date < now)
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        overdue_count = (await db.execute(overdue_count_stmt)).scalar() or 0

        if overdue_count > 0:
            # Get sample tasks for display
            overdue_tasks_stmt = (
                select(Task.key, Task.summary)
                .where(Task.project_id == project_id)
                .where(Task.due_date.is_not(None))
                .where(Task.due_date < now)
                .where(func.lower(Task.status).notin_(done_statuses))
                .limit(5)
            )
            overdue_tasks = (await db.execute(overdue_tasks_stmt)).mappings().all()

            risks.append(
                {
                    "type": "overdue_tasks",
                    "severity": "high" if overdue_count > 5 else "medium",
                    "count": overdue_count,
                    "tasks": [{"key": t["key"], "summary": t["summary"]} for t in overdue_tasks],
                }
            )

        # Risk 2: Blocked tasks
        blocked_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.is_blocker == True)
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        blocked_count = (await db.execute(blocked_count_stmt)).scalar() or 0

        if blocked_count > 0:
            # Get sample tasks for display
            blocked_tasks_stmt = (
                select(Task.key, Task.summary)
                .where(Task.project_id == project_id)
                .where(Task.is_blocker == True)
                .where(func.lower(Task.status).notin_(done_statuses))
                .limit(5)
            )
            blocked_tasks = (await db.execute(blocked_tasks_stmt)).mappings().all()

            risks.append(
                {
                    "type": "blocked_tasks",
                    "severity": "high",
                    "count": blocked_count,
                    "tasks": [{"key": t["key"], "summary": t["summary"]} for t in blocked_tasks],
                }
            )

        # Risk 3: Unestimated tasks
        unestimated_count_stmt = (
            select(func.count(Task.id))
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_(None))
            .where(func.lower(Task.status).notin_(done_statuses))
        )
        unestimated_count = (await db.execute(unestimated_count_stmt)).scalar() or 0

        if unestimated_count > 3:
            risks.append(
                {
                    "type": "unestimated_tasks",
                    "severity": "medium",
                    "count": unestimated_count,
                }
            )

        # Risk 4: Budget overruns (spent_hours > estimate_hours)
        overrun_stmt = (
            select(
                func.count(Task.id).label("count"),
                func.sum(Task.spent_hours - Task.estimate_hours).label("total_overrun")
            )
            .where(Task.project_id == project_id)
            .where(Task.estimate_hours.is_not(None))
            .where(Task.spent_hours > Task.estimate_hours)
        )
        overrun_result = (await db.execute(overrun_stmt)).mappings().first()
        overrun_count = overrun_result["count"] or 0
        total_overrun = _as_float(overrun_result["total_overrun"])

        if overrun_count > 0:
            risks.append(
                {
                    "type": "budget_overrun",
                    "severity": "high" if total_overrun > 40 else "medium",
                    "count": overrun_count,
                    "total_overrun_hours": round(total_overrun, 2),
                }
            )

        risk_score = sum(3 if r.get("severity") == "high" else 2 if r.get("severity") == "medium" else 1 for r in risks)
        risk_level = "critical" if risk_score > 9 else "high" if risk_score > 6 else "medium" if risk_score > 3 else "low"
        return {
            "risk_level": risk_level,
            "risk_score": risk_score,
            "total_risks": len(risks),
            "risks": risks,
        }
    except SQLAlchemyError as exc:
        logger.warning("identify_project_risks(%s) failed: %s", project_id, exc)
        return {"risk_level": "unknown", "risk_score": 0, "total_risks": 0, "risks": [], "error": "db_error"}

@router.get("/projects/{project_id}/forecast")
async def forecast_completion(project_id: int, db: AsyncSession = Depends(get_db)):
    try:
        velocity_data = await get_project_velocity(project_id, 5, db)  # type: ignore[arg-type]
        avg_velocity = _as_float(velocity_data.get("average_velocity"))

        remaining_stmt = (
            select(func.sum(Task.estimate_hours))
            .where(Task.project_id == project_id)
            .where(func.lower(Task.status).notin_(list(DONE_STATUSES)))
        )
        remaining = _as_float((await db.execute(remaining_stmt)).scalar())

        forecast = round(remaining / avg_velocity, 2) if avg_velocity > 0 else None
        return {
            "average_velocity": round(avg_velocity, 2),
            "remaining_hours": round(remaining, 2),
            "forecast_sprints": forecast,
        }
    except SQLAlchemyError as exc:
        logger.warning("forecast_completion(%s) failed: %s", project_id, exc)
        return {
            "average_velocity": 0.0,
            "remaining_hours": 0.0,
            "forecast_sprints": None,
            "error": "db_error",
        }


@router.get("/test-trend")
async def test_trend(
    project_id: Optional[int] = Query(None),
    days: int = Query(14, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
):
    try:
        since = datetime.utcnow() - timedelta(days=days)
        day_col = func.date(TestResult.created_at)
        fail_case = case((TestResult.status == "failed", 1), else_=0)
        stmt = (
            select(
                day_col.label("day"),
                func.count().label("total"),
                func.sum(fail_case).label("failed"),
            )
            .where(TestResult.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await db.execute(stmt)).mappings().all()
        trend = [
            {
                "day": row["day"],
                "total": int(row["total"] or 0),
                "failed": int(row["failed"] or 0),
            }
            for row in rows
        ]
        return {"days": days, "project_id": project_id, "trend": trend}
    except SQLAlchemyError as exc:
        logger.warning("test_trend failed: %s", exc)
        return {"days": days, "project_id": project_id, "trend": [], "error": "db_error"}


@router.get("/coverage-trend")
async def coverage_trend(
    project_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    try:
        since = datetime.utcnow() - timedelta(days=days)
        day_col = func.date(CoverageReport.created_at)
        stmt = (
            select(
                day_col.label("day"),
                func.avg(CoverageReport.line_coverage).label("avg_line"),
                func.avg(CoverageReport.branch_coverage).label("avg_branch"),
                func.count().label("count"),
            )
            .where(CoverageReport.created_at >= since)
            .group_by(day_col)
            .order_by(day_col)
        )
        rows = (await db.execute(stmt)).mappings().all()
        trend = [
            {
                "day": row["day"],
                "avg_line": round(_as_float(row["avg_line"]), 4),
                "avg_branch": round(_as_float(row["avg_branch"]), 4),
                "count": int(row["count"] or 0),
            }
            for row in rows
        ]
        return {"days": days, "project_id": project_id, "trend": trend}
    except SQLAlchemyError as exc:
        logger.warning("coverage_trend failed: %s", exc)
        return {"days": days, "project_id": project_id, "trend": [], "error": "db_error"}


@router.get("/projects/{project_id}/forecast/pr")
async def project_pr_forecast(project_id: int, db: AsyncSession = Depends(get_db)):
    try:
        stmt = (
            select(
                func.count(PullRequest.id).label("total"),
                func.avg(PullRequest.cycle_time_hours).label("avg_cycle"),
                func.avg(PullRequest.lead_time_hours).label("avg_lead"),
                func.avg(PullRequest.time_to_first_review_hours).label("avg_first_review"),
            )
            .where(PullRequest.repository_id == project_id)
        )
        row = (await db.execute(stmt)).first()
        total = int(row.total or 0) if row and row.total is not None else 0
        avg_cycle = round(_as_float(row.avg_cycle), 2) if row and row.avg_cycle is not None else 0.0
        avg_lead = round(_as_float(row.avg_lead), 2) if row and row.avg_lead is not None else 0.0
        avg_first = round(_as_float(row.avg_first_review), 2) if row and row.avg_first_review is not None else 0.0
        return {
            "total": total,
            "avg_cycle_time_hours": avg_cycle,
            "avg_lead_time_hours": avg_lead,
            "avg_time_to_first_review_hours": avg_first,
        }
    except SQLAlchemyError as exc:
        logger.warning("project_pr_forecast(%s) failed: %s", project_id, exc)
        return {
            "total": 0,
            "avg_cycle_time_hours": 0.0,
            "avg_lead_time_hours": 0.0,
            "avg_time_to_first_review_hours": 0.0,
            "error": "db_error",
        }

