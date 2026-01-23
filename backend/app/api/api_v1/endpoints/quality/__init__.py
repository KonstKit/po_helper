"""Quality package - Modular endpoints for quality metrics and reporting.

This package splits the quality functionality into focused sub-modules:
- gates: Quality gate checks and GitHub status/check updates
- defects: Escaped defects CRUD operations
- metrics: Quality summary, trends, dashboard, and metrics calculation
- reports: Sprint quality report generation (PDF, Excel, JSON)
"""

from fastapi import APIRouter

from .gates import router as gates_router
from .defects import router as defects_router
from .metrics import router as metrics_router
from .reports import router as reports_router

# Create combined router
router = APIRouter()

# Include all sub-routers
router.include_router(gates_router, tags=["Quality - Gates"])
router.include_router(defects_router, tags=["Quality - Defects"])
router.include_router(metrics_router, tags=["Quality - Metrics"])
router.include_router(reports_router, tags=["Quality - Reports"])

__all__ = ["router"]
