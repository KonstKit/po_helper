"""Tests for traceability services: LinkService, ValidationRulesService, DerivationService, ImpactAnalysisService."""

import pytest
import pytest_asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.traceability import Artifact, ArtifactLink, AuditLog
from app.services.traceability import (
    LinkService,
    LinkCreationMethod,
    LinkType,
    ValidationRulesService,
    ValidationSeverity,
    ValidationStatus,
    RequirementMustHaveTest,
    TestMustVerifyRequirement,
    DerivationService,
    ImpactAnalysisService,
)
from app.services.confidence_scoring import ConfidenceScoringService


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


class MockAsyncSession:
    """Mock async database session."""

    def __init__(self):
        self.added = []
        self.deleted = []
        self.flushed = False
        self.committed = False
        self._execute_results = []

    def add(self, obj):
        self.added.append(obj)
        if hasattr(obj, "id") and obj.id is None:
            obj.id = len(self.added)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass

    def set_execute_results(self, results):
        """Set results for execute calls."""
        self._execute_results = list(results)

    async def execute(self, stmt):
        if self._execute_results:
            return self._execute_results.pop(0)
        return MockResult([])


class MockResult:
    """Mock SQLAlchemy result."""

    def __init__(self, data, scalar_data=None):
        self._data = data
        self._scalar_data = scalar_data

    def scalars(self):
        return MockScalars(self._data)

    def scalar(self):
        return self._scalar_data

    def scalar_one_or_none(self):
        return self._data[0] if self._data else None

    def all(self):
        return self._data


class MockScalars:
    """Mock scalars result."""

    def __init__(self, data):
        self._data = data

    def all(self):
        return self._data

    def first(self):
        return self._data[0] if self._data else None


def create_mock_artifact(
    id: int,
    type: str = "requirement",
    external_id: str = None,
    project_id: int = 1,
    title: str = None,
    status: str = None,
) -> MagicMock:
    """Create a mock Artifact."""
    artifact = MagicMock(spec=Artifact)
    artifact.id = id
    artifact.type = type
    artifact.external_id = external_id or f"EXT-{id}"
    artifact.display_key = external_id or f"KEY-{id}"
    artifact.project_id = project_id
    artifact.title = title or f"Artifact {id}"
    artifact.status = status or "active"
    artifact.source = "jira"
    artifact.meta = {}
    artifact.created_at = datetime.utcnow()
    artifact.tenant_id = None
    return artifact


def create_mock_link(
    id: int,
    from_artifact_id: int,
    to_artifact_id: int,
    link_type: str = "implements",
    confidence: float = 0.8,
    project_id: int = 1,
) -> MagicMock:
    """Create a mock ArtifactLink."""
    link = MagicMock(spec=ArtifactLink)
    link.id = id
    link.from_artifact_id = from_artifact_id
    link.to_artifact_id = to_artifact_id
    link.link_type = link_type
    link.confidence = confidence
    link.project_id = project_id
    link.tenant_id = None
    link.created_via = "manual"
    link.confidence_factors = None
    link.created_at = datetime.utcnow()
    return link


# -----------------------------------------------------------------------------
# LinkService Tests
# -----------------------------------------------------------------------------


class TestLinkService:
    """Tests for LinkService."""

    @pytest.mark.asyncio
    async def test_create_link_success(self):
        """Test successful link creation."""
        db = MockAsyncSession()

        # Mock artifact lookup
        art1 = create_mock_artifact(1, "requirement")
        art2 = create_mock_artifact(2, "jira_issue")

        db.set_execute_results([
            MockResult([art1, art2]),  # Artifact lookup
            MockResult([]),  # Cycle check (empty = no cycle)
        ])

        service = LinkService(db)

        # Mock confidence calculation
        with patch.object(service, "_calculate_link_confidence", return_value=(0.85, {"test": 1})):
            link = await service.create_link(
                from_artifact_id=1,
                to_artifact_id=2,
                link_type="implements",
                created_by_id=1,
                calculate_confidence=True,
                create_audit=False,
            )

        assert len(db.added) >= 1
        assert db.flushed

    @pytest.mark.asyncio
    async def test_create_link_self_reference_fails(self):
        """Test that self-referencing links are rejected."""
        db = MockAsyncSession()
        service = LinkService(db)

        with pytest.raises(ValueError, match="Cannot create self-referencing"):
            await service.create_link(
                from_artifact_id=1,
                to_artifact_id=1,
                link_type="implements",
            )

    @pytest.mark.asyncio
    async def test_get_outgoing_links(self):
        """Test getting outgoing links."""
        db = MockAsyncSession()
        link1 = create_mock_link(1, 1, 2)
        link2 = create_mock_link(2, 1, 3)

        db.set_execute_results([MockResult([link1, link2])])

        service = LinkService(db)
        links = await service.get_outgoing_links(1)

        assert len(links) == 2

    @pytest.mark.asyncio
    async def test_delete_link(self):
        """Test link deletion."""
        db = MockAsyncSession()
        link = create_mock_link(1, 1, 2)

        db.set_execute_results([MockResult([link])])

        service = LinkService(db)
        result = await service.delete_link(1, create_audit=False)

        assert result is True
        assert link in db.deleted


# -----------------------------------------------------------------------------
# ValidationRulesService Tests
# -----------------------------------------------------------------------------


class TestValidationRulesService:
    """Tests for ValidationRulesService."""

    @pytest.mark.asyncio
    async def test_get_rules_returns_default_rules(self):
        """Test that default rules are returned."""
        db = MockAsyncSession()
        service = ValidationRulesService(db)

        rules = service.get_rules()

        assert len(rules) > 0
        rule_ids = [r["rule_id"] for r in rules]
        assert "REQ_MUST_HAVE_TEST" in rule_ids
        assert "TEST_MUST_VERIFY_REQ" in rule_ids

    @pytest.mark.asyncio
    async def test_requirement_must_have_test_fails(self):
        """Test that requirement without test fails validation."""
        db = MockAsyncSession()
        db.set_execute_results([MockResult([], scalar_data=0)])  # No test links

        artifact = create_mock_artifact(1, "requirement")

        rule = RequirementMustHaveTest()
        violation = await rule.validate(db, artifact, {})

        assert violation is not None
        assert violation.rule_id == "REQ_MUST_HAVE_TEST"
        assert violation.severity == ValidationSeverity.MUST

    @pytest.mark.asyncio
    async def test_requirement_with_test_passes(self):
        """Test that requirement with test passes validation."""
        db = MockAsyncSession()
        db.set_execute_results([MockResult([], scalar_data=1)])  # Has 1 test link

        artifact = create_mock_artifact(1, "requirement")

        rule = RequirementMustHaveTest()
        violation = await rule.validate(db, artifact, {})

        assert violation is None

    @pytest.mark.asyncio
    async def test_validate_artifact_applies_correct_rules(self):
        """Test that only applicable rules are run."""
        db = MockAsyncSession()
        db.set_execute_results([
            MockResult([], scalar_data=0),  # RequirementMustHaveTest
            MockResult([], scalar_data=0),  # ArtifactMustHaveAtLeastOneLink
        ])

        artifact = create_mock_artifact(1, "requirement")

        service = ValidationRulesService(db)
        violations = await service.validate_artifact(artifact)

        # Should have violations from applicable rules
        assert len(violations) >= 1

    @pytest.mark.asyncio
    async def test_validate_project(self):
        """Test project-wide validation."""
        db = MockAsyncSession()

        artifacts = [
            create_mock_artifact(1, "requirement"),
            create_mock_artifact(2, "test_case"),
        ]

        # Mock responses for project validation
        db.set_execute_results([
            MockResult(artifacts),  # Artifact query
            MockResult([], scalar_data=0),  # First artifact validation
            MockResult([], scalar_data=0),  # ArtifactMustHaveAtLeastOneLink
            MockResult([], scalar_data=0),  # Second artifact validation
            MockResult([], scalar_data=0),  # ArtifactMustHaveAtLeastOneLink
        ])

        service = ValidationRulesService(db)
        result = await service.validate_project(1, limit=10)

        assert result.total_checked == 2
        assert result.status in [ValidationStatus.PASS, ValidationStatus.FAIL, ValidationStatus.WARN]


# -----------------------------------------------------------------------------
# DerivationService Tests
# -----------------------------------------------------------------------------


class TestDerivationService:
    """Tests for DerivationService."""

    @pytest.mark.asyncio
    async def test_find_paths_direct(self):
        """Test finding direct paths between artifacts."""
        db = MockAsyncSession()

        # Mock: artifact 1 -> artifact 2 directly
        link = create_mock_link(1, 1, 2, "implements")

        db.set_execute_results([
            MockResult([link]),  # First query
            MockResult([]),  # No more links
        ])

        service = DerivationService(db)
        paths = await service.find_paths(1, 2, max_depth=3)

        assert len(paths) == 1
        assert paths[0].path == [1, 2]
        assert paths[0].path_length == 1

    @pytest.mark.asyncio
    async def test_find_paths_no_path(self):
        """Test when no path exists."""
        db = MockAsyncSession()
        db.set_execute_results([MockResult([])])  # No links

        service = DerivationService(db)
        paths = await service.find_paths(1, 10, max_depth=3)

        assert len(paths) == 0

    @pytest.mark.asyncio
    async def test_get_derivation_stats(self):
        """Test derivation statistics."""
        db = MockAsyncSession()
        db.set_execute_results([
            MockResult([], scalar_data=5),  # Total count
            MockResult([("requirement_to_commit", 3), ("requirement_to_test", 2)]),  # By type
            MockResult([], scalar_data=0.75),  # Avg confidence
        ])

        service = DerivationService(db)
        stats = await service.get_derivation_stats(1)

        assert "total_derived_links" in stats
        assert "by_type" in stats


# -----------------------------------------------------------------------------
# ImpactAnalysisService Tests
# -----------------------------------------------------------------------------


class TestImpactAnalysisService:
    """Tests for ImpactAnalysisService."""

    @pytest.mark.asyncio
    async def test_analyze_forward_impact(self):
        """Test forward impact analysis."""
        db = MockAsyncSession()

        root = create_mock_artifact(1, "requirement", "REQ-1")
        target = create_mock_artifact(2, "jira_issue", "JIRA-1")
        link = create_mock_link(1, 1, 2, "implements")

        db.set_execute_results([
            MockResult([root]),  # Root artifact lookup
            MockResult([(link, target)]),  # Forward links from root
            MockResult([target]),  # Target artifact lookup
            MockResult([]),  # No more forward links
        ])

        service = ImpactAnalysisService(db)
        analysis = await service.analyze_forward_impact(1, max_depth=2)

        assert analysis.root_artifact_id == 1
        assert analysis.direction == "forward"
        assert analysis.total_impacted >= 0

    @pytest.mark.asyncio
    async def test_compute_coverage_metrics(self):
        """Test coverage metrics computation."""
        db = MockAsyncSession()

        artifacts = [
            create_mock_artifact(1, "requirement"),
            create_mock_artifact(2, "requirement"),
            create_mock_artifact(3, "test_case"),
        ]

        links = [
            create_mock_link(1, 1, 3),  # artifact 1 linked
        ]

        db.set_execute_results([
            MockResult(artifacts),  # Artifacts query
            MockResult(links),  # Links query
        ])

        service = ImpactAnalysisService(db)
        metrics = await service.compute_coverage_metrics(1)

        assert metrics.total_artifacts == 3
        assert metrics.linked_artifacts >= 0
        assert 0 <= metrics.coverage_pct <= 100

    @pytest.mark.asyncio
    async def test_find_orphan_artifacts(self):
        """Test finding orphan artifacts."""
        db = MockAsyncSession()

        artifacts = [
            create_mock_artifact(1, "requirement"),
            create_mock_artifact(2, "jira_issue"),
        ]

        # Only artifact 1 has a link
        links = [(1, 3)]  # from_id, to_id

        db.set_execute_results([
            MockResult(artifacts),  # Artifacts query
            MockResult(links),  # Links query
        ])

        service = ImpactAnalysisService(db)
        orphans = await service.find_orphan_artifacts(1)

        # Artifact 2 should be an orphan (not in any link)
        orphan_ids = [o["id"] for o in orphans]
        assert 2 in orphan_ids


# -----------------------------------------------------------------------------
# ConfidenceScoringService Tests
# -----------------------------------------------------------------------------


class TestConfidenceScoringService:
    """Tests for ConfidenceScoringService."""

    def test_calculate_confidence_basic(self):
        """Test basic confidence calculation."""
        service = ConfidenceScoringService()

        from_artifact = {
            "id": 1,
            "type": "commit",
            "external_id": "abc123",
            "title": "Fix JIRA-123 bug",
            "meta": {"message": "JIRA-123: Fix authentication bug"},
        }

        to_artifact = {
            "id": 2,
            "type": "jira_issue",
            "external_id": "JIRA-123",
            "display_key": "JIRA-123",
            "title": "Authentication bug",
        }

        confidence, factors = service.calculate_confidence(
            from_artifact, to_artifact, "implements"
        )

        assert 0 <= confidence <= 1
        assert "text_similarity" in factors
        assert "explicit_reference" in factors

    def test_explicit_reference_detected(self):
        """Test that explicit key references boost confidence."""
        service = ConfidenceScoringService()

        from_artifact = {
            "id": 1,
            "type": "commit",
            "external_id": "abc123",
            "title": "PROJ-456: Add feature",
            "meta": {},
        }

        to_artifact = {
            "id": 2,
            "type": "jira_issue",
            "external_id": "PROJ-456",
            "display_key": "PROJ-456",
            "title": "Add new feature",
        }

        confidence, factors = service.calculate_confidence(
            from_artifact, to_artifact, "implements"
        )

        # Explicit reference should give high score
        assert factors["explicit_reference"] >= 0.5

    def test_temporal_proximity(self):
        """Test temporal proximity scoring."""
        service = ConfidenceScoringService()

        from_artifact = {
            "id": 1,
            "type": "commit",
            "created_at": datetime.utcnow(),
        }

        to_artifact = {
            "id": 2,
            "type": "jira_issue",
            "created_at": datetime.utcnow(),
        }

        confidence, factors = service.calculate_confidence(
            from_artifact, to_artifact, "implements"
        )

        # Same-day artifacts should have high temporal proximity
        assert factors["temporal_proximity"] >= 0.8


# -----------------------------------------------------------------------------
# normalize_confidence Tests
# -----------------------------------------------------------------------------


class TestNormalizeConfidence:
    """Tests for normalize_confidence function."""

    def test_normalize_confidence_none(self):
        """Test None value returns None."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(None) is None

    def test_normalize_confidence_valid_01_scale(self):
        """Test valid 0..1 scale values pass through."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(0.0) == 0.0
        assert normalize_confidence(0.5) == 0.5
        assert normalize_confidence(1.0) == 1.0

    def test_normalize_confidence_legacy_0100_scale(self):
        """Test legacy 0..100 scale is converted to 0..1."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(50.0) == 0.5
        assert normalize_confidence(100.0) == 1.0
        assert normalize_confidence(75.0) == 0.75

    def test_normalize_confidence_nan_returns_none(self):
        """Test NaN value returns None."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(float("nan")) is None

    def test_normalize_confidence_inf_returns_none(self):
        """Test infinity values return None."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(float("inf")) is None
        assert normalize_confidence(float("-inf")) is None

    def test_normalize_confidence_negative_clamped_to_zero(self):
        """Test negative values are clamped to 0."""
        from app.utils.confidence import normalize_confidence

        assert normalize_confidence(-0.5) == 0.0
        assert normalize_confidence(-100) == 0.0

    def test_normalize_confidence_boundary_101(self):
        """Test boundary at 1.01 triggers legacy conversion."""
        from app.utils.confidence import normalize_confidence

        # 1.01 > 1.0 so treated as legacy 0..100 scale
        result = normalize_confidence(1.01)
        assert result == pytest.approx(0.0101, rel=1e-3)


# -----------------------------------------------------------------------------
# Rule Engine Cycle Detection Tests
# -----------------------------------------------------------------------------


class TestRuleEngineCycleDetection:
    """Tests for DAG cycle detection in rule engine."""

    def test_would_create_cycle_detects_direct_cycle(self):
        """Test detection of direct A->B->A cycle."""
        from app.services.traceability.engine.nodes.create_link_action import (
            CreateLinkActionExecutor,
            DAG_LINK_TYPES,
        )

        # Mock context with DB that returns links forming a cycle
        mock_db = MagicMock()

        # Existing: A(1) -> B(2). Now trying to add B(2) -> A(1).
        # BFS starts from to_id=1, looking for from_id=2.
        # From node 1, we query outgoing links -> returns [(2,)] meaning 1 links to 2.
        # Then we check: is 2 == from_id(2)? Yes! Cycle detected.
        mock_db.query.return_value.filter.return_value.all.return_value = [(2,)]  # Node 1 links to Node 2

        mock_context = MagicMock()
        mock_context.db = mock_db

        executor = CreateLinkActionExecutor()

        # Trying to add B(2) -> A(1). If A(1) -> B(2) exists, this creates cycle.
        result = executor._would_create_cycle(2, 1, "implements", mock_context)

        # Should detect cycle
        assert result is True

    def test_would_create_cycle_no_cycle(self):
        """Test no false positive when no cycle exists."""
        from app.services.traceability.engine.nodes.create_link_action import (
            CreateLinkActionExecutor,
        )

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []  # No outgoing links

        mock_context = MagicMock()
        mock_context.db = mock_db

        executor = CreateLinkActionExecutor()

        result = executor._would_create_cycle(1, 2, "implements", mock_context)

        # No cycle
        assert result is False

    def test_dag_link_types_defined(self):
        """Test DAG_LINK_TYPES contains expected hierarchical types."""
        from app.services.traceability.engine.nodes.create_link_action import DAG_LINK_TYPES

        assert "implements" in DAG_LINK_TYPES
        assert "tests" in DAG_LINK_TYPES
        assert "deploys" in DAG_LINK_TYPES
        assert "derives_from" in DAG_LINK_TYPES
        # Non-DAG types should not be included
        assert "relates_to" not in DAG_LINK_TYPES
