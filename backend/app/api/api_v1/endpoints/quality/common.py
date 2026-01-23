"""Common imports and utilities for quality endpoints."""

from __future__ import annotations

from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import requests

from fastapi import APIRouter, HTTPException, Depends, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, Integer, case
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import PullRequest, CoverageReport, Repository
from app.core.config import settings
from app.models import QualityGateHistory
from app.models.quality import EscapedDefect, DefectMetrics
from app.schemas.quality import (
    EscapedDefectCreate,
    EscapedDefectUpdate,
    EscapedDefect as EscapedDefectSchema,
    DefectMetricsCreate,
    DefectMetrics as DefectMetricsSchema,
    QualitySummary,
    QualityTrendData,
    DefectTrend,
    RootCauseAnalysis,
    ComponentAnalysis,
    QualityDashboard,
    ReportFormat,
    ReportSection,
    SprintQualityReport,
    ReportGenerationRequest,
    ReportGenerationResponse,
    TestCoverageSection,
    PRQualitySection,
    ComponentHealthItem,
)
from app.utils import transactional_session
from app.services.report_generator import ReportGeneratorService
from app.core.cache_enhanced import (
    cached_endpoint,
    CacheTier,
    QualityCacheKeys,
    CacheInvalidator,
)
from app.models.testing import (
    FlakyTest,
    CoverageHistory,
    ComponentCoverage as ComponentCoverageModel,
)
from app.models.project import Project
from app.models.sprint import Sprint


# Initialize report generator service
report_service = ReportGeneratorService()


async def persist_quality_history(
    payload: Dict[str, Any],
    result: Dict[str, Any],
    db: AsyncSession,
) -> None:
    """
    Persist quality gate assessment to history.

    This utility eliminates the repetitive 21-line pattern of:
    - Creating QualityGateHistory record
    - Populating all fields from payload and result
    - Persisting with transactional_session
    - Silently catching exceptions

    Args:
        payload: Input payload containing project_id, provider, pr_number, commit_sha
        result: Quality gate assessment result containing pass, coverage metrics, reasons
        db: Database session
    """
    try:
        rec = QualityGateHistory(
            project_id=payload.get("project_id"),
            provider=(payload.get("provider") or "").lower(),
            pr_number=payload.get("pr_number"),
            commit_sha=payload.get("commit_sha"),
            passed=bool(result.get("pass")) if "pass" in result else None,
            line_coverage=result.get("line_coverage"),
            branch_coverage=result.get("branch_coverage"),
            reasons=result.get("reasons"),
            result_payload=result,
        )
        async with transactional_session(db):
            db.add(rec)
    except Exception:
        pass


def check_gate_thresholds(
    line_cov: Optional[float],
    branch_cov: Optional[float],
    min_line: float,
    min_branch: Optional[float],
) -> Dict[str, Any]:
    """Check coverage against quality gate thresholds."""
    reasons = []
    ok = True
    if line_cov is None:
        reasons.append("no_line_coverage")
        ok = False
    elif line_cov < min_line:
        reasons.append(f"low_line_coverage:{line_cov:.2f}<{min_line:.2f}")
        ok = False
    if min_branch is not None:
        if branch_cov is None:
            reasons.append("no_branch_coverage")
            ok = False
        elif branch_cov < min_branch:
            reasons.append(f"low_branch_coverage:{branch_cov:.2f}<{min_branch:.2f}")
            ok = False
    return {"pass": ok, "reasons": reasons}


def severity_to_score(severity: str) -> int:
    """Convert severity to numeric score (4=critical, 1=low)."""
    return {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(severity, 2)


__all__ = [
    # Database & HTTP
    "get_db",
    "AsyncSession",
    "Depends",
    "Query",
    "HTTPException",
    "Response",
    "FileResponse",
    "APIRouter",
    # SQLAlchemy
    "select",
    "func",
    "and_",
    "or_",
    "Integer",
    "case",
    "selectinload",
    # Types
    "Optional",
    "Dict",
    "Any",
    "List",
    "datetime",
    "timedelta",
    "requests",
    # Models
    "PullRequest",
    "CoverageReport",
    "Repository",
    "QualityGateHistory",
    "EscapedDefect",
    "DefectMetrics",
    "FlakyTest",
    "CoverageHistory",
    "ComponentCoverageModel",
    "Project",
    "Sprint",
    # Schemas
    "EscapedDefectCreate",
    "EscapedDefectUpdate",
    "EscapedDefectSchema",
    "DefectMetricsCreate",
    "DefectMetricsSchema",
    "QualitySummary",
    "QualityTrendData",
    "DefectTrend",
    "RootCauseAnalysis",
    "ComponentAnalysis",
    "QualityDashboard",
    "ReportFormat",
    "ReportSection",
    "SprintQualityReport",
    "ReportGenerationRequest",
    "ReportGenerationResponse",
    "TestCoverageSection",
    "PRQualitySection",
    "ComponentHealthItem",
    # Config & Utils
    "settings",
    "transactional_session",
    "report_service",
    # Cache
    "cached_endpoint",
    "CacheTier",
    "QualityCacheKeys",
    "CacheInvalidator",
    # Helper functions
    "persist_quality_history",
    "check_gate_thresholds",
    "severity_to_score",
]
