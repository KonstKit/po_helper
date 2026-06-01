"""Validation Rules Service for enforcing traceability coverage rules.

This service provides:
- Configurable validation rules (e.g., "requirement must have ≥1 test")
- Coverage checks by artifact type
- Severity levels (MUST/SHOULD/WARN)
- Batch validation for projects
- Gap detection and reporting
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Artifact, ArtifactLink

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity level for validation rules."""

    MUST = "must"  # Fails validation
    SHOULD = "should"  # Warning, doesn't fail
    WARN = "warn"  # Informational only


class ValidationStatus(str, Enum):
    """Status of a validation check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"  # Rule doesn't apply


@dataclass
class ValidationViolation:
    """Represents a single validation violation."""

    rule_id: str
    rule_name: str
    severity: ValidationSeverity
    artifact_id: int
    artifact_type: str
    artifact_key: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of running validation rules."""

    status: ValidationStatus
    total_checked: int
    passed: int
    failed: int
    warnings: int
    violations: List[ValidationViolation]
    summary: Dict[str, Any]
    checked_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def coverage_pct(self) -> float:
        """Calculate coverage percentage."""
        if self.total_checked == 0:
            return 100.0
        return (self.passed / self.total_checked) * 100.0


class ValidationRule(ABC):
    """Abstract base class for validation rules."""

    rule_id: str
    name: str
    description: str
    severity: ValidationSeverity
    applies_to: Set[str]  # Artifact types this rule applies to

    @abstractmethod
    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        """
        Validate a single artifact against this rule.

        Returns:
            ValidationViolation if rule is violated, None if passed
        """
        pass


class RequirementMustHaveTest(ValidationRule):
    """Rule: Requirements must have at least one incoming 'tests' link."""

    rule_id = "REQ_MUST_HAVE_TEST"
    name = "Requirement Must Have Test"
    description = "Every requirement artifact must have at least one test case linked to it"
    severity = ValidationSeverity.MUST
    applies_to = {"requirement", "confluence_page"}  # Requirements often in Confluence

    def __init__(
        self,
        min_tests: int = 1,
        severity: ValidationSeverity = ValidationSeverity.MUST,
    ):
        self.min_tests = min_tests
        self.severity = severity

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # Count incoming "tests" or "verifies" links
        result = await db.execute(
            select(func.count(ArtifactLink.id)).where(
                ArtifactLink.to_artifact_id == artifact.id,
                ArtifactLink.link_type.in_(["tests", "verifies"]),
            )
        )
        test_count = result.scalar() or 0

        if test_count < self.min_tests:
            return ValidationViolation(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                artifact_key=artifact.display_key or artifact.external_id,
                message=f"Requirement has {test_count} test(s), requires at least {self.min_tests}",
                details={
                    "current_count": test_count,
                    "required_count": self.min_tests,
                    "link_types_checked": ["tests", "verifies"],
                },
            )

        return None


class TestMustVerifyRequirement(ValidationRule):
    """Rule: Test cases must verify at least one requirement."""

    rule_id = "TEST_MUST_VERIFY_REQ"
    name = "Test Must Verify Requirement"
    description = "Every test case must verify at least one requirement"
    severity = ValidationSeverity.SHOULD
    applies_to = {"test_case", "test_run"}

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # Count outgoing "tests" or "verifies" links to requirements
        result = await db.execute(
            select(func.count(ArtifactLink.id))
            .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
            .where(
                ArtifactLink.from_artifact_id == artifact.id,
                ArtifactLink.link_type.in_(["tests", "verifies"]),
                Artifact.type.in_(["requirement", "confluence_page", "jira_issue"]),
            )
        )
        req_count = result.scalar() or 0

        if req_count < 1:
            return ValidationViolation(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                artifact_key=artifact.display_key or artifact.external_id,
                message="Test case does not verify any requirement",
                details={"linked_requirements": 0},
            )

        return None


class CommitMustLinkToJira(ValidationRule):
    """Rule: Commits should link to at least one Jira issue."""

    rule_id = "COMMIT_MUST_LINK_JIRA"
    name = "Commit Must Link to Jira"
    description = "Every commit should reference at least one Jira issue"
    severity = ValidationSeverity.SHOULD
    applies_to = {"commit"}

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # Count outgoing links to jira_issue
        result = await db.execute(
            select(func.count(ArtifactLink.id))
            .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
            .where(
                ArtifactLink.from_artifact_id == artifact.id,
                Artifact.type == "jira_issue",
            )
        )
        jira_count = result.scalar() or 0

        if jira_count < 1:
            return ValidationViolation(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                artifact_key=artifact.display_key or artifact.external_id,
                message="Commit does not link to any Jira issue",
                details={"linked_jira_issues": 0},
            )

        return None


class JiraIssueMustHaveImplementation(ValidationRule):
    """Rule: Jira issues (stories/tasks) should have implementation links."""

    rule_id = "JIRA_MUST_HAVE_IMPL"
    name = "Jira Issue Must Have Implementation"
    description = "Development Jira issues should have commits or PRs linked"
    severity = ValidationSeverity.WARN
    applies_to = {"jira_issue"}

    def __init__(
        self,
        exclude_statuses: Optional[Set[str]] = None,
    ):
        # Exclude certain statuses (e.g., backlog items)
        self.exclude_statuses = exclude_statuses or {
            "backlog",
            "cancelled",
            "won't do",
            "duplicate",
        }

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # Skip if status is excluded
        status = (artifact.status or "").lower()
        if status in self.exclude_statuses:
            return None

        # Count incoming "implements" links from commits/PRs
        result = await db.execute(
            select(func.count(ArtifactLink.id))
            .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
            .where(
                ArtifactLink.to_artifact_id == artifact.id,
                ArtifactLink.link_type == "implements",
                Artifact.type.in_(["commit", "pr"]),
            )
        )
        impl_count = result.scalar() or 0

        if impl_count < 1:
            return ValidationViolation(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                artifact_key=artifact.display_key or artifact.external_id,
                message="Jira issue has no implementation (commits/PRs) linked",
                details={
                    "status": artifact.status,
                    "implementation_count": impl_count,
                },
            )

        return None


class ArtifactMustHaveAtLeastOneLink(ValidationRule):
    """Rule: Artifacts should not be orphans (should have at least one link)."""

    rule_id = "ARTIFACT_NOT_ORPHAN"
    name = "Artifact Must Not Be Orphan"
    description = "Every artifact should have at least one link (incoming or outgoing)"
    severity = ValidationSeverity.WARN
    applies_to = {
        "requirement",
        "jira_issue",
        "commit",
        "pr",
        "test_case",
        "confluence_page",
    }

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # Count total links (incoming + outgoing)
        result = await db.execute(
            select(func.count(ArtifactLink.id)).where(
                or_(
                    ArtifactLink.from_artifact_id == artifact.id,
                    ArtifactLink.to_artifact_id == artifact.id,
                )
            )
        )
        link_count = result.scalar() or 0

        if link_count < 1:
            return ValidationViolation(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                artifact_id=artifact.id,
                artifact_type=artifact.type,
                artifact_key=artifact.display_key or artifact.external_id,
                message="Artifact is an orphan with no links",
                details={"total_links": 0},
            )

        return None


class MinimumConfidenceRule(ValidationRule):
    """Rule: Links should have minimum confidence level."""

    rule_id = "LINK_MIN_CONFIDENCE"
    name = "Link Minimum Confidence"
    description = "Links should have confidence above threshold"
    severity = ValidationSeverity.WARN
    applies_to = set()  # Applied to links, not artifacts directly

    def __init__(
        self,
        min_confidence: float = 0.5,
        link_types: Optional[Set[str]] = None,
    ):
        self.min_confidence = min_confidence
        self.link_types = link_types or {"implements", "tests", "verifies"}

    async def validate(
        self,
        db: AsyncSession,
        artifact: Artifact,
        context: Dict[str, Any],
    ) -> Optional[ValidationViolation]:
        # This rule validates links, not artifacts
        # It's called from a different context
        return None


class ValidationRulesService:
    """Service for running validation rules against artifacts."""

    # Default rules - can be extended
    DEFAULT_RULES: List[Type[ValidationRule]] = [
        RequirementMustHaveTest,
        TestMustVerifyRequirement,
        CommitMustLinkToJira,
        JiraIssueMustHaveImplementation,
        ArtifactMustHaveAtLeastOneLink,
    ]

    def __init__(self, db: AsyncSession):
        self.db = db
        self._rules: List[ValidationRule] = []
        self._initialize_default_rules()

    def _initialize_default_rules(self) -> None:
        """Initialize with default rules."""
        for rule_class in self.DEFAULT_RULES:
            self._rules.append(rule_class())

    def add_rule(self, rule: ValidationRule) -> None:
        """Add a custom validation rule."""
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule by ID."""
        for i, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                self._rules.pop(i)
                return True
        return False

    def get_rules(self) -> List[Dict[str, Any]]:
        """Get list of all active rules."""
        return [
            {
                "rule_id": rule.rule_id,
                "name": rule.name,
                "description": rule.description,
                "severity": rule.severity.value,
                "applies_to": list(rule.applies_to),
            }
            for rule in self._rules
        ]

    async def validate_artifact(
        self,
        artifact: Artifact,
        *,
        rule_ids: Optional[Set[str]] = None,
        severities: Optional[Set[ValidationSeverity]] = None,
    ) -> List[ValidationViolation]:
        """
        Validate a single artifact against all applicable rules.

        Args:
            artifact: Artifact to validate
            rule_ids: Optional filter for specific rules
            severities: Optional filter for specific severities

        Returns:
            List of violations found
        """
        violations = []
        context = {}

        for rule in self._rules:
            # Filter by rule_ids
            if rule_ids and rule.rule_id not in rule_ids:
                continue

            # Filter by severity
            if severities and rule.severity not in severities:
                continue

            # Check if rule applies to this artifact type
            if artifact.type not in rule.applies_to:
                continue

            try:
                violation = await rule.validate(self.db, artifact, context)
                if violation:
                    violations.append(violation)
            except Exception as e:
                logger.error(
                    "Error validating artifact %s with rule %s: %s",
                    artifact.id,
                    rule.rule_id,
                    e,
                )

        return violations

    async def validate_project(
        self,
        project_id: int,
        *,
        artifact_types: Optional[Set[str]] = None,
        rule_ids: Optional[Set[str]] = None,
        severities: Optional[Set[ValidationSeverity]] = None,
        limit: int = 10000,
    ) -> ValidationResult:
        """
        Validate all artifacts in a project.

        Args:
            project_id: Project to validate
            artifact_types: Optional filter for artifact types
            rule_ids: Optional filter for specific rules
            severities: Optional filter for specific severities
            limit: Max artifacts to check

        Returns:
            ValidationResult with all violations
        """
        # Fetch artifacts
        stmt = select(Artifact).where(Artifact.project_id == project_id)

        if artifact_types:
            stmt = stmt.where(Artifact.type.in_(artifact_types))

        stmt = stmt.limit(limit)
        result = await self.db.execute(stmt)
        artifacts = result.scalars().all()

        all_violations: List[ValidationViolation] = []
        passed = 0
        failed = 0
        warnings = 0

        for artifact in artifacts:
            violations = await self.validate_artifact(
                artifact,
                rule_ids=rule_ids,
                severities=severities,
            )

            if violations:
                all_violations.extend(violations)
                # Check if any are MUST violations
                has_must_violation = any(v.severity == ValidationSeverity.MUST for v in violations)
                if has_must_violation:
                    failed += 1
                else:
                    warnings += 1
            else:
                passed += 1

        # Determine overall status
        if failed > 0:
            status = ValidationStatus.FAIL
        elif warnings > 0:
            status = ValidationStatus.WARN
        else:
            status = ValidationStatus.PASS

        # Build summary by rule
        summary_by_rule: Dict[str, Dict[str, int]] = {}
        for v in all_violations:
            if v.rule_id not in summary_by_rule:
                summary_by_rule[v.rule_id] = {"violations": 0, "rule_name": v.rule_name}
            summary_by_rule[v.rule_id]["violations"] += 1

        return ValidationResult(
            status=status,
            total_checked=len(artifacts),
            passed=passed,
            failed=failed,
            warnings=warnings,
            violations=all_violations,
            summary={
                "by_rule": summary_by_rule,
                "by_severity": {
                    "must": len(
                        [v for v in all_violations if v.severity == ValidationSeverity.MUST]
                    ),
                    "should": len(
                        [v for v in all_violations if v.severity == ValidationSeverity.SHOULD]
                    ),
                    "warn": len(
                        [v for v in all_violations if v.severity == ValidationSeverity.WARN]
                    ),
                },
                "by_artifact_type": self._group_by_artifact_type(all_violations),
            },
        )

    async def get_coverage_gaps(
        self,
        project_id: int,
        *,
        artifact_type: str = "requirement",
        link_type: str = "tests",
    ) -> Dict[str, Any]:
        """
        Find artifacts that lack specific link coverage.

        Args:
            project_id: Project to check
            artifact_type: Type of artifacts to check
            link_type: Link type to check for

        Returns:
            Dict with uncovered artifacts and statistics
        """
        # Get all artifacts of type
        artifacts_stmt = select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.type == artifact_type,
        )
        result = await self.db.execute(artifacts_stmt)
        artifacts = result.scalars().all()

        # Get artifacts with the specified link type
        covered_stmt = select(ArtifactLink.to_artifact_id).where(
            ArtifactLink.link_type == link_type,
            ArtifactLink.to_artifact_id.in_([a.id for a in artifacts]),
        )
        covered_result = await self.db.execute(covered_stmt)
        covered_ids = {row[0] for row in covered_result.all()}

        uncovered = [
            {
                "id": a.id,
                "type": a.type,
                "external_id": a.external_id,
                "display_key": a.display_key,
                "title": a.title,
                "status": a.status,
            }
            for a in artifacts
            if a.id not in covered_ids
        ]

        total = len(artifacts)
        covered_count = len(covered_ids)

        return {
            "artifact_type": artifact_type,
            "link_type": link_type,
            "total": total,
            "covered": covered_count,
            "uncovered_count": total - covered_count,
            "coverage_pct": (covered_count / total * 100) if total > 0 else 100.0,
            "uncovered_artifacts": uncovered,
        }

    def _group_by_artifact_type(
        self,
        violations: List[ValidationViolation],
    ) -> Dict[str, int]:
        """Group violations by artifact type."""
        result: Dict[str, int] = {}
        for v in violations:
            result[v.artifact_type] = result.get(v.artifact_type, 0) + 1
        return result


# Factory function for dependency injection
def get_validation_rules_service(db: AsyncSession) -> ValidationRulesService:
    """Get ValidationRulesService instance."""
    return ValidationRulesService(db)
