"""Validation endpoints for traceability coverage enforcement.

Provides endpoints to:
- Validate artifacts against coverage rules
- Get coverage gaps
- Configure validation rules
- Run project-wide validation
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models import Artifact, User, Permissions
from app.api.deps import ensure_project_access, require_permission
from app.services.traceability import (
    ValidationSeverity,
    get_validation_rules_service,
)

router = APIRouter()


class ValidationRequest(BaseModel):
    """Request body for project validation."""

    artifact_types: Optional[List[str]] = None
    rule_ids: Optional[List[str]] = None
    severities: Optional[List[str]] = None
    limit: int = 10000


class CoverageGapRequest(BaseModel):
    """Request body for coverage gap analysis."""

    source_type: str = "requirement"
    target_type: str = "test_case"
    required_link_types: Optional[List[str]] = None


@router.get("/validation/rules")
async def list_validation_rules(
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
    db: AsyncSession = Depends(get_db),
):
    """
    Get list of all available validation rules.

    Returns rule definitions including:
    - rule_id: Unique identifier
    - name: Human-readable name
    - description: What the rule validates
    - severity: MUST (fails validation) / SHOULD (warning) / WARN (info)
    - applies_to: Artifact types this rule checks
    """
    service = get_validation_rules_service(db)
    rules = service.get_rules()

    return {
        "rules": rules,
        "total": len(rules),
        "severities": [s.value for s in ValidationSeverity],
    }


@router.get("/validation/artifact/{artifact_id}")
async def validate_artifact(
    artifact_id: int,
    rule_ids: Optional[str] = Query(None, description="Comma-separated rule IDs to run"),
    severities: Optional[str] = Query(None, description="Comma-separated severities to include"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Validate a single artifact against all applicable rules.

    Returns list of violations if any rules fail.
    """
    # Get artifact
    result = await db.execute(select(Artifact).where(Artifact.id == artifact_id))
    artifact = result.scalar_one_or_none()

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    if artifact.project_id:
        await ensure_project_access(artifact.project_id, db, current_user)

    # Parse filters
    rule_id_set = set(rule_ids.split(",")) if rule_ids else None
    severity_set = (
        {ValidationSeverity(s.strip()) for s in severities.split(",")} if severities else None
    )

    # Validate
    service = get_validation_rules_service(db)
    violations = await service.validate_artifact(
        artifact,
        rule_ids=rule_id_set,
        severities=severity_set,
    )

    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact.type,
        "artifact_key": artifact.display_key or artifact.external_id,
        "is_valid": len(violations) == 0,
        "violations": [
            {
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "severity": v.severity.value,
                "message": v.message,
                "details": v.details,
            }
            for v in violations
        ],
        "violation_count": len(violations),
    }


@router.post("/validation/project/{project_id}")
async def validate_project(
    project_id: int,
    request: ValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Run validation on all artifacts in a project.

    Returns aggregated validation results with:
    - Overall pass/fail status
    - All violations grouped by rule
    - Statistics by artifact type and severity
    """
    await ensure_project_access(project_id, db, current_user)

    # Parse filters
    artifact_types = set(request.artifact_types) if request.artifact_types else None
    rule_ids = set(request.rule_ids) if request.rule_ids else None
    severities = {ValidationSeverity(s) for s in request.severities} if request.severities else None

    # Validate
    service = get_validation_rules_service(db)
    result = await service.validate_project(
        project_id,
        artifact_types=artifact_types,
        rule_ids=rule_ids,
        severities=severities,
        limit=request.limit,
    )

    return {
        "project_id": project_id,
        "status": result.status.value,
        "coverage_pct": round(result.coverage_pct, 2),
        "total_checked": result.total_checked,
        "passed": result.passed,
        "failed": result.failed,
        "warnings": result.warnings,
        "summary": result.summary,
        "violations": [
            {
                "rule_id": v.rule_id,
                "rule_name": v.rule_name,
                "severity": v.severity.value,
                "artifact_id": v.artifact_id,
                "artifact_type": v.artifact_type,
                "artifact_key": v.artifact_key,
                "message": v.message,
                "details": v.details,
            }
            for v in result.violations
        ],
        "checked_at": result.checked_at.isoformat(),
    }


@router.post("/validation/coverage-gaps/{project_id}")
async def get_coverage_gaps(
    project_id: int,
    request: CoverageGapRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Find artifacts that lack required coverage.

    For example: requirements without linked test cases.

    Returns:
    - List of uncovered artifacts
    - Coverage percentage
    - Statistics
    """
    await ensure_project_access(project_id, db, current_user)

    service = get_validation_rules_service(db)
    gaps = await service.get_coverage_gaps(
        project_id,
        artifact_type=request.source_type,
        link_type=request.required_link_types[0] if request.required_link_types else "tests",
    )

    return gaps


@router.get("/validation/quick-stats/{project_id}")
async def get_quick_validation_stats(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.TRACEABILITY_VIEW)),
):
    """
    Get quick validation statistics for a project.

    Runs a subset of critical rules for fast feedback.
    """
    await ensure_project_access(project_id, db, current_user)

    # Only run MUST rules for quick stats
    service = get_validation_rules_service(db)
    result = await service.validate_project(
        project_id,
        severities={ValidationSeverity.MUST},
        limit=1000,  # Limited for speed
    )

    # Calculate percentages by artifact type
    by_type = {}
    for v in result.violations:
        if v.artifact_type not in by_type:
            by_type[v.artifact_type] = 0
        by_type[v.artifact_type] += 1

    return {
        "project_id": project_id,
        "is_compliant": result.failed == 0,
        "compliance_score": round(result.coverage_pct, 1),
        "total_checked": result.total_checked,
        "critical_violations": result.failed,
        "violations_by_type": by_type,
    }
