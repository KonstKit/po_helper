"""Traceability services package.

This package contains services for managing traceability artifacts,
links, validation rules, derived links, and impact analysis.
"""

from .engine import RuleExecutionEngine
from .link_service import (
    LinkService,
    LinkCreationMethod,
    LinkType,
    REVERSE_LINK_TYPES,
    get_link_service,
)
from .validation_rules import (
    ValidationRulesService,
    ValidationRule,
    ValidationSeverity,
    ValidationStatus,
    ValidationResult,
    ValidationViolation,
    RequirementMustHaveTest,
    TestMustVerifyRequirement,
    CommitMustLinkToJira,
    JiraIssueMustHaveImplementation,
    ArtifactMustHaveAtLeastOneLink,
    get_validation_rules_service,
)
from .derivation_service import (
    DerivationService,
    TracePath,
    DerivedLink,
    get_derivation_service,
)
from .impact_service import (
    ImpactAnalysisService,
    ImpactNode,
    ImpactAnalysis,
    CoverageMetrics,
    get_impact_analysis_service,
)

__all__ = [
    # Engine
    "RuleExecutionEngine",
    # Link Service
    "LinkService",
    "LinkCreationMethod",
    "LinkType",
    "REVERSE_LINK_TYPES",
    "get_link_service",
    # Validation
    "ValidationRulesService",
    "ValidationRule",
    "ValidationSeverity",
    "ValidationStatus",
    "ValidationResult",
    "ValidationViolation",
    "RequirementMustHaveTest",
    "TestMustVerifyRequirement",
    "CommitMustLinkToJira",
    "JiraIssueMustHaveImplementation",
    "ArtifactMustHaveAtLeastOneLink",
    "get_validation_rules_service",
    # Derivation
    "DerivationService",
    "TracePath",
    "DerivedLink",
    "get_derivation_service",
    # Impact Analysis
    "ImpactAnalysisService",
    "ImpactNode",
    "ImpactAnalysis",
    "CoverageMetrics",
    "get_impact_analysis_service",
]
