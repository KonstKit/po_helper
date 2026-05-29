"""Traceability package - Modular endpoints for traceability features.

This package splits the traceability functionality into focused sub-modules:
- links: Core link operations, backfill, autolink
- rules: Traceability rules CRUD and execution
- analysis: Full chain traversal and impact analysis
- orphans: Orphaned artifacts and confidence scoring
- suggestions: TF-IDF-based link suggestions with approval queue
- health: Sync health monitoring and consistency checks
- matrix: RTM matrix, coverage analytics, saved configs, exports
- validation: Coverage validation rules and gap analysis
- derivation: Derived/materialized links and path finding
"""

from fastapi import APIRouter

from .links import router as links_router
from .rules import router as rules_router
from .analysis import router as analysis_router
from .orphans import router as orphans_router
from .suggestions import router as suggestions_router
from .health import router as health_router
from .baselines import router as baselines_router
from .projections import router as projections_router
from .connector_configs import router as connector_configs_router
from .audit import router as audit_router
from .sync_tasks import router as sync_tasks_router
from .matrix import router as matrix_router
from .validation import router as validation_router
from .derivation import router as derivation_router
from .review import router as review_router

# Create combined router
router = APIRouter()

# Include all sub-routers
router.include_router(links_router, tags=["Traceability - Links"])
router.include_router(rules_router, tags=["Traceability - Rules"])
router.include_router(analysis_router, tags=["Traceability - Analysis"])
router.include_router(orphans_router, tags=["Traceability - Orphans"])
router.include_router(suggestions_router, tags=["Traceability - Suggestions"])
router.include_router(health_router, tags=["Traceability - Health"])
router.include_router(baselines_router, tags=["Traceability - Baselines"])
router.include_router(projections_router, tags=["Traceability - Projections"])
router.include_router(connector_configs_router, tags=["Traceability - Connector Configs"])
router.include_router(audit_router, tags=["Traceability - Audit"])
router.include_router(sync_tasks_router, tags=["Traceability - Sync Tasks"])
router.include_router(matrix_router, tags=["Traceability - RTM Matrix"])
router.include_router(validation_router, tags=["Traceability - Validation"])
router.include_router(derivation_router, tags=["Traceability - Derivation"])
router.include_router(review_router, tags=["Traceability - Review Queue"])

__all__ = ["router"]
