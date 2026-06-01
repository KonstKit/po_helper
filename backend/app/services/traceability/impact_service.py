"""Impact Analysis Service for traceability impact assessment.

This service provides:
- Forward impact analysis (what does this artifact affect?)
- Backward impact analysis (what does this artifact depend on?)
- Coverage metrics computation
- Gap identification
- Change impact assessment
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Artifact, ArtifactLink
from app.utils.confidence import normalize_confidence, confidence_filter

logger = logging.getLogger(__name__)


@dataclass
class ImpactNode:
    """Represents a node in the impact analysis graph."""

    artifact_id: int
    artifact_type: str
    external_id: str
    display_key: Optional[str]
    title: Optional[str]
    status: Optional[str]
    depth: int
    link_type: str  # How it's connected to parent
    confidence: Optional[float]


@dataclass
class ImpactAnalysis:
    """Result of impact analysis."""

    root_artifact_id: int
    root_type: str
    root_key: str
    direction: str  # "forward" or "backward"
    total_impacted: int
    max_depth: int
    impacted_artifacts: List[ImpactNode]
    by_type: Dict[str, int]
    by_depth: Dict[int, int]
    by_link_type: Dict[str, int]
    low_confidence_links: int
    analyzed_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "root_artifact_id": self.root_artifact_id,
            "root_type": self.root_type,
            "root_key": self.root_key,
            "direction": self.direction,
            "total_impacted": self.total_impacted,
            "max_depth": self.max_depth,
            "impacted_artifacts": [
                {
                    "artifact_id": n.artifact_id,
                    "artifact_type": n.artifact_type,
                    "external_id": n.external_id,
                    "display_key": n.display_key,
                    "title": n.title,
                    "status": n.status,
                    "depth": n.depth,
                    "link_type": n.link_type,
                    "confidence": n.confidence,
                }
                for n in self.impacted_artifacts
            ],
            "by_type": self.by_type,
            "by_depth": self.by_depth,
            "by_link_type": self.by_link_type,
            "low_confidence_links": self.low_confidence_links,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class CoverageMetrics:
    """Coverage metrics for a project or artifact type."""

    total_artifacts: int
    linked_artifacts: int
    unlinked_artifacts: int
    coverage_pct: float
    by_type: Dict[str, Dict[str, int]]
    by_link_type: Dict[str, int]
    avg_links_per_artifact: float
    high_confidence_links: int
    low_confidence_links: int


class ImpactAnalysisService:
    """Service for analyzing traceability impact."""

    # Confidence threshold for "low confidence" classification
    LOW_CONFIDENCE_THRESHOLD = 0.5

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Forward Impact Analysis
    # -------------------------------------------------------------------------

    async def analyze_forward_impact(
        self,
        artifact_id: int,
        *,
        max_depth: int = 5,
        link_types: Optional[Set[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> ImpactAnalysis:
        """
        Analyze forward impact: what artifacts are affected by changes to this artifact?

        Follows outgoing links from the artifact.

        Args:
            artifact_id: Starting artifact
            max_depth: Maximum depth to traverse
            link_types: Filter to specific link types
            min_confidence: Minimum confidence threshold
            project_id: Filter to specific project

        Returns:
            ImpactAnalysis result
        """
        # Get root artifact
        root = await self._get_artifact(artifact_id)
        if not root:
            raise ValueError(f"Artifact {artifact_id} not found")

        impacted = await self._traverse_impact(
            artifact_id,
            direction="forward",
            max_depth=max_depth,
            link_types=link_types,
            min_confidence=min_confidence,
            project_id=project_id,
        )

        return self._build_impact_analysis(root, impacted, "forward", max_depth)

    async def analyze_backward_impact(
        self,
        artifact_id: int,
        *,
        max_depth: int = 5,
        link_types: Optional[Set[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> ImpactAnalysis:
        """
        Analyze backward impact: what artifacts does this artifact depend on?

        Follows incoming links to the artifact.

        Args:
            artifact_id: Starting artifact
            max_depth: Maximum depth to traverse
            link_types: Filter to specific link types
            min_confidence: Minimum confidence threshold
            project_id: Filter to specific project

        Returns:
            ImpactAnalysis result
        """
        # Get root artifact
        root = await self._get_artifact(artifact_id)
        if not root:
            raise ValueError(f"Artifact {artifact_id} not found")

        impacted = await self._traverse_impact(
            artifact_id,
            direction="backward",
            max_depth=max_depth,
            link_types=link_types,
            min_confidence=min_confidence,
            project_id=project_id,
        )

        return self._build_impact_analysis(root, impacted, "backward", max_depth)

    async def analyze_full_impact(
        self,
        artifact_id: int,
        *,
        max_depth: int = 5,
        link_types: Optional[Set[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> Dict[str, ImpactAnalysis]:
        """
        Analyze both forward and backward impact.

        Returns:
            Dict with "forward" and "backward" ImpactAnalysis
        """
        forward = await self.analyze_forward_impact(
            artifact_id,
            max_depth=max_depth,
            link_types=link_types,
            min_confidence=min_confidence,
            project_id=project_id,
        )

        backward = await self.analyze_backward_impact(
            artifact_id,
            max_depth=max_depth,
            link_types=link_types,
            min_confidence=min_confidence,
            project_id=project_id,
        )

        return {"forward": forward, "backward": backward}

    # -------------------------------------------------------------------------
    # Coverage Metrics
    # -------------------------------------------------------------------------

    async def compute_coverage_metrics(
        self,
        project_id: int,
        *,
        artifact_types: Optional[Set[str]] = None,
    ) -> CoverageMetrics:
        """
        Compute coverage metrics for a project.

        Args:
            project_id: Project to analyze
            artifact_types: Filter to specific artifact types

        Returns:
            CoverageMetrics with detailed statistics
        """
        # Get all artifacts
        artifact_stmt = select(Artifact).where(Artifact.project_id == project_id)
        if artifact_types:
            artifact_stmt = artifact_stmt.where(Artifact.type.in_(artifact_types))

        result = await self.db.execute(artifact_stmt)
        artifacts = result.scalars().all()

        if not artifacts:
            return CoverageMetrics(
                total_artifacts=0,
                linked_artifacts=0,
                unlinked_artifacts=0,
                coverage_pct=100.0,
                by_type={},
                by_link_type={},
                avg_links_per_artifact=0.0,
                high_confidence_links=0,
                low_confidence_links=0,
            )

        artifact_ids = [a.id for a in artifacts]

        # Get all links for these artifacts
        links_stmt = select(ArtifactLink).where(
            or_(
                ArtifactLink.from_artifact_id.in_(artifact_ids),
                ArtifactLink.to_artifact_id.in_(artifact_ids),
            )
        )
        links_result = await self.db.execute(links_stmt)
        links = links_result.scalars().all()

        # Count linked artifacts
        linked_ids: Set[int] = set()
        for link in links:
            if link.from_artifact_id in artifact_ids:
                linked_ids.add(link.from_artifact_id)
            if link.to_artifact_id in artifact_ids:
                linked_ids.add(link.to_artifact_id)

        # Compute by-type metrics
        by_type: Dict[str, Dict[str, int]] = {}
        for artifact in artifacts:
            if artifact.type not in by_type:
                by_type[artifact.type] = {"total": 0, "linked": 0, "unlinked": 0}
            by_type[artifact.type]["total"] += 1
            if artifact.id in linked_ids:
                by_type[artifact.type]["linked"] += 1
            else:
                by_type[artifact.type]["unlinked"] += 1

        # By link type
        by_link_type: Dict[str, int] = {}
        high_confidence = 0
        low_confidence = 0

        for link in links:
            by_link_type[link.link_type] = by_link_type.get(link.link_type, 0) + 1
            if link.confidence is not None:
                # Normalize legacy 0..100 confidence values to 0..1 scale
                normalized_conf = normalize_confidence(link.confidence)
                if normalized_conf is not None and normalized_conf >= self.LOW_CONFIDENCE_THRESHOLD:
                    high_confidence += 1
                else:
                    low_confidence += 1

        total = len(artifacts)
        linked = len(linked_ids)

        return CoverageMetrics(
            total_artifacts=total,
            linked_artifacts=linked,
            unlinked_artifacts=total - linked,
            coverage_pct=(linked / total * 100) if total > 0 else 100.0,
            by_type=by_type,
            by_link_type=by_link_type,
            avg_links_per_artifact=len(links) / total if total > 0 else 0.0,
            high_confidence_links=high_confidence,
            low_confidence_links=low_confidence,
        )

    # -------------------------------------------------------------------------
    # Gap Analysis
    # -------------------------------------------------------------------------

    async def find_coverage_gaps(
        self,
        project_id: int,
        *,
        source_type: str = "requirement",
        target_type: str = "test_case",
        required_link_types: Optional[Set[str]] = None,
    ) -> Dict[str, Any]:
        """
        Find artifacts that lack required coverage.

        For example: requirements without test cases.

        Args:
            project_id: Project to analyze
            source_type: Source artifact type to check
            target_type: Target artifact type that should be linked
            required_link_types: Link types that satisfy coverage

        Returns:
            Dict with uncovered artifacts and statistics
        """
        link_types = required_link_types or {"tests", "verifies"}

        # Get all source artifacts
        source_stmt = select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.type == source_type,
        )
        source_result = await self.db.execute(source_stmt)
        sources = source_result.scalars().all()

        if not sources:
            return {
                "source_type": source_type,
                "target_type": target_type,
                "required_link_types": list(link_types),
                "total": 0,
                "covered": 0,
                "gaps": 0,
                "coverage_pct": 100.0,
                "gap_artifacts": [],
            }

        source_ids = [a.id for a in sources]

        # Find sources that have the required links
        covered_stmt = (
            select(ArtifactLink.to_artifact_id)
            .distinct()
            .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
            .where(
                ArtifactLink.to_artifact_id.in_(source_ids),
                ArtifactLink.link_type.in_(link_types),
                Artifact.type == target_type,
            )
        )
        covered_result = await self.db.execute(covered_stmt)
        covered_ids = {row[0] for row in covered_result.all()}

        # Identify gaps
        gaps = [
            {
                "id": a.id,
                "type": a.type,
                "external_id": a.external_id,
                "display_key": a.display_key,
                "title": a.title,
                "status": a.status,
            }
            for a in sources
            if a.id not in covered_ids
        ]

        total = len(sources)
        covered_count = len(covered_ids)

        return {
            "source_type": source_type,
            "target_type": target_type,
            "required_link_types": list(link_types),
            "total": total,
            "covered": covered_count,
            "gaps": total - covered_count,
            "coverage_pct": (covered_count / total * 100) if total > 0 else 100.0,
            "gap_artifacts": gaps,
        }

    async def find_orphan_artifacts(
        self,
        project_id: int,
        *,
        artifact_types: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find artifacts with no links (orphans).

        Args:
            project_id: Project to analyze
            artifact_types: Filter to specific types

        Returns:
            List of orphan artifacts
        """
        # Get all artifacts
        artifact_stmt = select(Artifact).where(Artifact.project_id == project_id)
        if artifact_types:
            artifact_stmt = artifact_stmt.where(Artifact.type.in_(artifact_types))

        artifact_result = await self.db.execute(artifact_stmt)
        artifacts = artifact_result.scalars().all()

        artifact_ids = [a.id for a in artifacts]

        if not artifact_ids:
            return []

        # Find linked artifact IDs
        linked_stmt = select(ArtifactLink.from_artifact_id, ArtifactLink.to_artifact_id).where(
            or_(
                ArtifactLink.from_artifact_id.in_(artifact_ids),
                ArtifactLink.to_artifact_id.in_(artifact_ids),
            )
        )
        linked_result = await self.db.execute(linked_stmt)
        linked_ids: Set[int] = set()
        for from_id, to_id in linked_result.all():
            linked_ids.add(from_id)
            linked_ids.add(to_id)

        # Orphans are artifacts not in linked_ids
        orphans = [
            {
                "id": a.id,
                "type": a.type,
                "external_id": a.external_id,
                "display_key": a.display_key,
                "title": a.title,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in artifacts
            if a.id not in linked_ids
        ]

        return orphans

    # -------------------------------------------------------------------------
    # Change Impact Assessment
    # -------------------------------------------------------------------------

    async def assess_change_impact(
        self,
        artifact_ids: List[int],
        *,
        max_depth: int = 3,
        project_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Assess the impact of changing multiple artifacts.

        Args:
            artifact_ids: Artifacts being changed
            max_depth: Maximum depth for impact traversal
            project_id: Filter to specific project

        Returns:
            Dict with aggregated impact assessment
        """
        all_impacted: Dict[int, ImpactNode] = {}
        all_by_type: Dict[str, int] = {}
        all_by_link_type: Dict[str, int] = {}

        for artifact_id in artifact_ids:
            try:
                analysis = await self.analyze_forward_impact(
                    artifact_id,
                    max_depth=max_depth,
                    project_id=project_id,
                )

                for node in analysis.impacted_artifacts:
                    if node.artifact_id not in all_impacted:
                        all_impacted[node.artifact_id] = node

                for type_name, count in analysis.by_type.items():
                    all_by_type[type_name] = all_by_type.get(type_name, 0) + count

                for link_type, count in analysis.by_link_type.items():
                    all_by_link_type[link_type] = all_by_link_type.get(link_type, 0) + count

            except ValueError:
                # Artifact not found, skip
                continue

        return {
            "changed_artifacts": artifact_ids,
            "total_impacted": len(all_impacted),
            "unique_impacted_artifacts": [
                {
                    "artifact_id": n.artifact_id,
                    "artifact_type": n.artifact_type,
                    "external_id": n.external_id,
                    "title": n.title,
                    "depth": n.depth,
                }
                for n in all_impacted.values()
            ],
            "by_type": all_by_type,
            "by_link_type": all_by_link_type,
            "risk_level": self._calculate_risk_level(len(all_impacted), all_by_type),
        }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    async def _get_artifact(self, artifact_id: int) -> Optional[Artifact]:
        """Get artifact by ID."""
        result = await self.db.execute(select(Artifact).where(Artifact.id == artifact_id))
        return result.scalar_one_or_none()

    async def _traverse_impact(
        self,
        start_id: int,
        direction: str,
        max_depth: int,
        link_types: Optional[Set[str]],
        min_confidence: Optional[float],
        project_id: Optional[int],
    ) -> List[ImpactNode]:
        """BFS traversal for impact analysis."""
        impacted: List[ImpactNode] = []
        visited = {start_id}

        # Queue: (artifact_id, depth, link_type, confidence)
        queue: List[Tuple[int, int, str, Optional[float]]] = []

        # Get initial links
        if direction == "forward":
            stmt = (
                select(ArtifactLink, Artifact)
                .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
                .where(ArtifactLink.from_artifact_id == start_id)
            )
        else:
            stmt = (
                select(ArtifactLink, Artifact)
                .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
                .where(ArtifactLink.to_artifact_id == start_id)
            )

        if link_types:
            stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
        if min_confidence is not None:
            # Use confidence_filter to handle legacy 0..100 data normalization
            stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))
        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)

        result = await self.db.execute(stmt)
        for link, artifact in result.all():
            next_id = artifact.id
            queue.append((next_id, 1, link.link_type, link.confidence))

        while queue:
            current_id, depth, link_type, confidence = queue.pop(0)

            if current_id in visited:
                continue
            if depth > max_depth:
                continue

            visited.add(current_id)

            # Get artifact details
            artifact = await self._get_artifact(current_id)
            if not artifact:
                continue

            impacted.append(
                ImpactNode(
                    artifact_id=artifact.id,
                    artifact_type=artifact.type,
                    external_id=artifact.external_id,
                    display_key=artifact.display_key,
                    title=artifact.title,
                    status=artifact.status,
                    depth=depth,
                    link_type=link_type,
                    confidence=confidence,
                )
            )

            # Get next level links
            if direction == "forward":
                next_stmt = (
                    select(ArtifactLink, Artifact)
                    .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
                    .where(ArtifactLink.from_artifact_id == current_id)
                )
            else:
                next_stmt = (
                    select(ArtifactLink, Artifact)
                    .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
                    .where(ArtifactLink.to_artifact_id == current_id)
                )

            if link_types:
                next_stmt = next_stmt.where(ArtifactLink.link_type.in_(link_types))
            if min_confidence is not None:
                # Use confidence_filter to handle legacy 0..100 data normalization
                next_stmt = next_stmt.where(
                    confidence_filter(ArtifactLink.confidence, min_confidence)
                )
            if project_id is not None:
                next_stmt = next_stmt.where(ArtifactLink.project_id == project_id)

            next_result = await self.db.execute(next_stmt)
            for next_link, next_artifact in next_result.all():
                next_id = next_artifact.id
                if next_id not in visited:
                    queue.append((next_id, depth + 1, next_link.link_type, next_link.confidence))

        return impacted

    def _build_impact_analysis(
        self,
        root: Artifact,
        impacted: List[ImpactNode],
        direction: str,
        max_depth: int,
    ) -> ImpactAnalysis:
        """Build ImpactAnalysis result."""
        by_type: Dict[str, int] = {}
        by_depth: Dict[int, int] = {}
        by_link_type: Dict[str, int] = {}
        low_confidence = 0

        for node in impacted:
            by_type[node.artifact_type] = by_type.get(node.artifact_type, 0) + 1
            by_depth[node.depth] = by_depth.get(node.depth, 0) + 1
            by_link_type[node.link_type] = by_link_type.get(node.link_type, 0) + 1

            # Normalize legacy 0..100 confidence values to 0..1 scale
            normalized_node_conf = normalize_confidence(node.confidence)
            if (
                normalized_node_conf is not None
                and normalized_node_conf < self.LOW_CONFIDENCE_THRESHOLD
            ):
                low_confidence += 1

        return ImpactAnalysis(
            root_artifact_id=root.id,
            root_type=root.type,
            root_key=root.display_key or root.external_id,
            direction=direction,
            total_impacted=len(impacted),
            max_depth=max(by_depth.keys()) if by_depth else 0,
            impacted_artifacts=impacted,
            by_type=by_type,
            by_depth=by_depth,
            by_link_type=by_link_type,
            low_confidence_links=low_confidence,
        )

    def _calculate_risk_level(
        self,
        impacted_count: int,
        by_type: Dict[str, int],
    ) -> str:
        """Calculate risk level based on impact scope."""
        # High risk if many artifacts or critical types affected
        critical_types = {"requirement", "deployment", "pipeline"}
        critical_count = sum(by_type.get(t, 0) for t in critical_types)

        if impacted_count > 50 or critical_count > 10:
            return "high"
        elif impacted_count > 20 or critical_count > 5:
            return "medium"
        else:
            return "low"


# Factory function for dependency injection
def get_impact_analysis_service(db: AsyncSession) -> ImpactAnalysisService:
    """Get ImpactAnalysisService instance."""
    return ImpactAnalysisService(db)
