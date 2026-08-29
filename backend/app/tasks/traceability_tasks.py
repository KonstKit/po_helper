"""Celery tasks for traceability operations.

Provides scheduled tasks for:
- Rule execution (cron-based)
- Derived link recomputation
- Validation checks
- Materialization updates
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

from app.core.celery_async_runner import run_async
from app.core.celery_app import TASK_RETRY_KWARGS, celery_app
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def _execute_rule_async(rule_id: int, trigger: str = "scheduled") -> Dict[str, Any]:
    """Execute a traceability rule asynchronously (default trigger: scheduled)."""
    from app.services.traceability.engine import RuleExecutionEngine

    # Note: RuleExecutionEngine uses sync SQLAlchemy, need sync session
    from app.core.database import SessionLocal

    with SessionLocal() as sync_db:
        engine = RuleExecutionEngine(sync_db)
        result = engine.execute_rule(rule_id, trigger=trigger)
        return result


async def _execute_all_enabled_rules_async(
    project_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Execute all enabled rules for a project."""
    from sqlalchemy import select
    from app.models.traceability_rule import TraceabilityRule
    from app.core.database import SessionLocal

    results = []

    with SessionLocal() as db:
        stmt = select(TraceabilityRule).where(TraceabilityRule.enabled.is_(True))
        if project_id:
            stmt = stmt.where(TraceabilityRule.project_id == project_id)

        rules = db.execute(stmt).scalars().all()

        from app.services.traceability.engine import RuleExecutionEngine

        for rule in rules:
            try:
                engine = RuleExecutionEngine(db)
                result = engine.execute_rule(rule.id, trigger="scheduled")
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "status": result.get("status"),
                        "links_created": result.get("links_created", 0),
                    }
                )
            except Exception as e:
                logger.error("Error executing rule %d: %s", rule.id, e)
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "status": "error",
                        "error": str(e),
                    }
                )

    return results


async def _generate_suggestions_async(project_id: int) -> Dict[str, Any]:
    """Generate and store TF-IDF suggestions for a project."""
    from app.services.text_similarity import get_similarity_service

    async with AsyncSessionLocal() as db:
        service = get_similarity_service()
        suggestions = await service.generate_suggestions(
            db,
            project_id=project_id,
            rebuild_index=True,
        )
        stored = await service.store_suggestions(db, suggestions, project_id=project_id)
        return {
            "project_id": project_id,
            "generated": len(suggestions),
            "stored": stored,
        }


async def _execute_sync_complete_rules_async(
    project_id: int,
    *,
    source: Optional[str] = None,
    trigger: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute rules that opt into sync-complete triggers."""
    from sqlalchemy import or_, select

    from app.core.database import SessionLocal
    from app.models.traceability_rule import TraceabilityRule
    from app.services.traceability.engine import RuleExecutionEngine

    results: List[Dict[str, Any]] = []

    with SessionLocal() as db:
        stmt = select(TraceabilityRule).where(
            TraceabilityRule.enabled.is_(True),
            TraceabilityRule.execute_on_sync_complete.is_(True),
            or_(TraceabilityRule.project_id == project_id, TraceabilityRule.project_id.is_(None)),
        )
        rules = db.execute(stmt).scalars().all()

        engine = RuleExecutionEngine(db)
        for rule in rules:
            try:
                result = engine.execute_rule(rule.id, trigger="post_sync")
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "status": result.get("status"),
                        "links_created": result.get("links_created", 0),
                        "project_id": project_id,
                        "source": source,
                        "trigger": trigger,
                    }
                )
            except Exception as exc:
                logger.error(
                    "Error executing sync-complete rule %d for project %d: %s",
                    rule.id,
                    project_id,
                    exc,
                )
                results.append(
                    {
                        "rule_id": rule.id,
                        "rule_name": rule.name,
                        "status": "error",
                        "error": str(exc),
                        "project_id": project_id,
                        "source": source,
                        "trigger": trigger,
                    }
                )

    return results


async def _recompute_derived_links_async(
    project_id: int,
    from_type: str = "requirement",
    to_type: str = "commit",
) -> Dict[str, Any]:
    """Recompute derived links for a project."""
    from app.services.traceability import get_derivation_service

    async with AsyncSessionLocal() as db:
        service = get_derivation_service(db)

        # Compute derived links
        derived = await service.compute_derived_links(
            project_id,
            from_type=from_type,
            to_type=to_type,
            max_depth=3,
        )

        # Materialize with overwrite
        created, skipped = await service.materialize_derived_links(
            project_id,
            derived,
            overwrite=True,
        )

        await db.commit()

        return {
            "project_id": project_id,
            "from_type": from_type,
            "to_type": to_type,
            "computed": len(derived),
            "created": created,
            "skipped": skipped,
        }


async def _validate_project_async(project_id: int) -> Dict[str, Any]:
    """Run validation on a project."""
    from app.services.traceability import get_validation_rules_service

    async with AsyncSessionLocal() as db:
        service = get_validation_rules_service(db)
        result = await service.validate_project(project_id)

        return {
            "project_id": project_id,
            "status": result.status.value,
            "total_checked": result.total_checked,
            "passed": result.passed,
            "failed": result.failed,
            "warnings": result.warnings,
            "coverage_pct": round(result.coverage_pct, 2),
        }


# -----------------------------------------------------------------------------
# Celery Tasks
# -----------------------------------------------------------------------------


@celery_app.task(name="traceability.execute_rule", **TASK_RETRY_KWARGS)
def execute_rule_task(rule_id: int) -> Dict[str, Any]:
    """
    Execute a single traceability rule.

    Called by scheduler or webhook trigger.
    """
    logger.info("Executing traceability rule %d", rule_id)
    try:
        result = run_async(_execute_rule_async(rule_id))
        logger.info(
            "Rule %d executed: status=%s, links_created=%d",
            rule_id,
            result.get("status"),
            result.get("links_created", 0),
        )
        return result
    except Exception as e:
        logger.error("Error executing rule %d: %s", rule_id, e)
        return {"rule_id": rule_id, "status": "error", "error": str(e)}


@celery_app.task(name="traceability.execute_all_rules", **TASK_RETRY_KWARGS)
def execute_all_rules_task(project_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Execute all enabled traceability rules.

    Optionally filter by project_id.
    """
    logger.info("Executing all enabled rules (project_id=%s)", project_id)
    results = run_async(_execute_all_enabled_rules_async(project_id))
    logger.info("Executed %d rules", len(results))
    return results


@celery_app.task(name="traceability.generate_suggestions", **TASK_RETRY_KWARGS)
def generate_suggestions_task(project_id: int) -> Dict[str, Any]:
    """Generate TF-IDF suggestions after artifact ingestion."""
    logger.info("Generating traceability suggestions for project %d", project_id)
    result = run_async(_generate_suggestions_async(project_id))
    logger.info(
        "Traceability suggestions generated for project %d: generated=%d stored=%d",
        project_id,
        result.get("generated", 0),
        result.get("stored", 0),
    )
    return result


@celery_app.task(name="traceability.execute_sync_complete_rules", **TASK_RETRY_KWARGS)
def execute_sync_complete_rules_task(
    project_id: int,
    source: Optional[str] = None,
    trigger: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute rules that opt into sync-complete automation."""
    logger.info(
        "Executing sync-complete traceability rules for project %d (source=%s trigger=%s)",
        project_id,
        source,
        trigger,
    )
    results = run_async(
        _execute_sync_complete_rules_async(project_id, source=source, trigger=trigger)
    )
    logger.info(
        "Executed %d sync-complete rules for project %d",
        len(results),
        project_id,
    )
    return results


@celery_app.task(name="traceability.recompute_derived_links", **TASK_RETRY_KWARGS)
def recompute_derived_links_task(
    project_id: int,
    from_type: str = "requirement",
    to_type: str = "commit",
) -> Dict[str, Any]:
    """
    Recompute and materialize derived links for a project.

    This task computes transitive relationships and persists them
    for faster querying.
    """
    logger.info(
        "Recomputing derived links for project %d: %s -> %s",
        project_id,
        from_type,
        to_type,
    )
    result = run_async(_recompute_derived_links_async(project_id, from_type, to_type))
    logger.info(
        "Derived links recomputed: computed=%d, created=%d",
        result.get("computed", 0),
        result.get("created", 0),
    )
    return result


@celery_app.task(name="traceability.validate_project", **TASK_RETRY_KWARGS)
def validate_project_task(project_id: int) -> Dict[str, Any]:
    """
    Run validation rules on a project.

    Returns summary of validation results.
    """
    logger.info("Running validation for project %d", project_id)
    result = run_async(_validate_project_async(project_id))
    logger.info(
        "Validation complete: status=%s, coverage=%.1f%%",
        result.get("status"),
        result.get("coverage_pct", 0),
    )
    return result


@celery_app.task(name="traceability.scheduled_rule_execution", **TASK_RETRY_KWARGS)
def scheduled_rule_execution_task() -> Dict[str, Any]:
    """
    Check and execute rules based on their cron schedules.

    This task should be called periodically (e.g., every minute)
    to check which rules are due for execution.
    """
    from sqlalchemy import select
    from app.models.traceability_rule import TraceabilityRule
    from app.core.database import SessionLocal
    from croniter import croniter

    logger.info("Checking scheduled rules")
    now = datetime.now(timezone.utc)
    executed = []

    with SessionLocal() as db:
        # Get enabled rules with active scheduling policy
        stmt = select(TraceabilityRule).where(
            TraceabilityRule.enabled.is_(True),
            TraceabilityRule.schedule_enabled.is_(True),
            TraceabilityRule.schedule_cron.isnot(None),
        )
        rules = db.execute(stmt).scalars().all()
        changed = False

        for rule in rules:
            try:
                # First-time setup: schedule exists but next run has not been calculated yet.
                if rule.next_scheduled_run is None:
                    cron = croniter(cast(str, rule.schedule_cron), now)
                    rule.next_scheduled_run = cron.get_next(datetime)
                    changed = True
                    continue

                next_run = rule.next_scheduled_run
                if next_run.tzinfo is None:
                    next_run = next_run.replace(tzinfo=timezone.utc)

                # If next run is now or in the past, execute and move pointer forward.
                if next_run <= now:
                    logger.info("Executing scheduled rule %d: %s", rule.id, rule.name)
                    execute_rule_task.delay(rule.id)

                    cron = croniter(cast(str, rule.schedule_cron), now)
                    rule.next_scheduled_run = cron.get_next(datetime)
                    changed = True

                    executed.append(
                        {
                            "rule_id": rule.id,
                            "rule_name": rule.name,
                            "schedule_cron": rule.schedule_cron,
                        }
                    )

            except Exception as e:
                # Invalid cron/config should not create infinite error loops.
                logger.error(
                    "Error checking schedule for rule %d: %s",
                    rule.id,
                    e,
                )
                rule.schedule_enabled = False
                rule.next_scheduled_run = None
                changed = True

        if changed:
            db.commit()

    return {
        "checked_at": now.isoformat(),
        "rules_checked": len(rules) if "rules" in dir() else 0,
        "rules_executed": executed,
    }


@celery_app.task(name="traceability.batch_materialize", **TASK_RETRY_KWARGS)
def batch_materialize_task(project_id: int) -> Dict[str, Any]:
    """
    Batch materialization of all derived link types for a project.

    Materializes:
    - requirement -> commit
    - requirement -> test_run
    - confluence_page -> commit
    """
    logger.info("Batch materializing derived links for project %d", project_id)

    derivation_configs = [
        ("requirement", "commit"),
        ("requirement", "test_run"),
        ("confluence_page", "commit"),
    ]

    results = []
    for from_type, to_type in derivation_configs:
        try:
            result = run_async(_recompute_derived_links_async(project_id, from_type, to_type))
            results.append(result)
        except Exception as e:
            logger.error(
                "Error materializing %s -> %s: %s",
                from_type,
                to_type,
                e,
            )
            results.append(
                {
                    "from_type": from_type,
                    "to_type": to_type,
                    "error": str(e),
                }
            )

    return {
        "project_id": project_id,
        "results": results,
    }
