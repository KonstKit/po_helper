"""Derivation Service for computing and materializing derived links.

This service provides:
- Path computation between artifacts (e.g., requirement → jira → commit)
- Materialized (derived) link creation and storage
- Automatic invalidation on updates
- Path metadata storage
- Transitive closure computation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, func, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traceability import Artifact, ArtifactLink
from app.utils.confidence import confidence_filter, normalize_confidence

logger = logging.getLogger(__name__)


@dataclass
class TracePath:
    """Represents a path through the traceability graph."""

    start_artifact_id: int
    end_artifact_id: int
    path: List[int]  # List of artifact IDs in order
    links: List[int]  # List of link IDs used
    link_types: List[str]  # Link types traversed
    total_confidence: float
    min_confidence: float
    path_length: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "start_artifact_id": self.start_artifact_id,
            "end_artifact_id": self.end_artifact_id,
            "path": self.path,
            "links": self.links,
            "link_types": self.link_types,
            "total_confidence": self.total_confidence,
            "min_confidence": self.min_confidence,
            "path_length": self.path_length,
        }


@dataclass
class DerivedLink:
    """Represents a derived (materialized) link."""

    from_artifact_id: int
    to_artifact_id: int
    derived_type: str  # The semantic meaning of the derivation
    paths: List[TracePath]
    combined_confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# Common derivation patterns
DERIVATION_PATTERNS = {
    "requirement_to_commit": {
        "name": "Requirement to Commit",
        "description": "Derive link from requirement to commit via Jira issue",
        "path_types": [
            ["implements"],  # requirement <- jira via implements
            ["relates_to", "implements"],  # requirement -> jira -> commit
        ],
        "derived_type": "traced_to",
    },
    "requirement_to_test_run": {
        "name": "Requirement to Test Run",
        "description": "Derive link from requirement to test execution",
        "path_types": [
            ["tests"],  # requirement <- test_case via tests
            ["tests", "executes"],  # requirement <- test_case <- test_run
        ],
        "derived_type": "verified_by",
    },
    "confluence_to_commit": {
        "name": "Confluence to Commit",
        "description": "Derive link from Confluence page to commits via Jira",
        "path_types": [
            ["implements"],  # page <- jira via implements
            ["relates_to", "implements"],  # page -> jira -> commit
        ],
        "derived_type": "implemented_by",
    },
}


class DerivationService:
    """Service for computing and materializing derived traceability links."""

    # Derived links are stored with this source_system
    DERIVED_SOURCE_SYSTEM = "derivation_service"

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Path Finding
    # -------------------------------------------------------------------------

    async def find_paths(
        self,
        start_artifact_id: int,
        end_artifact_id: int,
        *,
        max_depth: int = 5,
        link_types: Optional[Set[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> List[TracePath]:
        """
        Find all paths between two artifacts using BFS.

        Args:
            start_artifact_id: Starting artifact
            end_artifact_id: Target artifact
            max_depth: Maximum path length
            link_types: Filter to specific link types
            min_confidence: Minimum confidence threshold
            project_id: Filter to specific project

        Returns:
            List of TracePath objects
        """
        paths: List[TracePath] = []

        # BFS with path tracking
        # Each queue item: (current_id, path_ids, link_ids, link_types, confidences)
        queue: List[Tuple[int, List[int], List[int], List[str], List[float]]] = [
            (start_artifact_id, [start_artifact_id], [], [], [])
        ]
        visited_paths: Set[tuple] = set()

        while queue:
            current_id, path_ids, link_ids, types, confidences = queue.pop(0)

            if len(path_ids) > max_depth + 1:
                continue

            # Check if reached target
            if current_id == end_artifact_id and len(path_ids) > 1:
                path_tuple = tuple(path_ids)
                if path_tuple not in visited_paths:
                    visited_paths.add(path_tuple)
                    total_conf = 1.0
                    for c in confidences:
                        total_conf *= c if c else 1.0

                    paths.append(
                        TracePath(
                            start_artifact_id=start_artifact_id,
                            end_artifact_id=end_artifact_id,
                            path=path_ids,
                            links=link_ids,
                            link_types=types,
                            total_confidence=total_conf,
                            min_confidence=min(confidences) if confidences else 1.0,
                            path_length=len(path_ids) - 1,
                        )
                    )
                continue

            # Get outgoing links
            stmt = select(ArtifactLink).where(ArtifactLink.from_artifact_id == current_id)

            if link_types:
                stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
            if min_confidence is not None:
                stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))
            if project_id is not None:
                stmt = stmt.where(ArtifactLink.project_id == project_id)

            result = await self.db.execute(stmt)
            links = result.scalars().all()

            for link in links:
                next_id = link.to_artifact_id
                if next_id not in path_ids:  # Avoid cycles
                    new_path = path_ids + [next_id]
                    new_links = link_ids + [link.id]
                    new_types = types + [link.link_type]
                    normalized_conf = normalize_confidence(link.confidence) or 1.0
                    new_confs = confidences + [normalized_conf]
                    queue.append((next_id, new_path, new_links, new_types, new_confs))

        return sorted(paths, key=lambda p: (-p.min_confidence, p.path_length))

    async def find_all_reachable(
        self,
        start_artifact_id: int,
        *,
        direction: str = "outgoing",  # "outgoing", "incoming", "both"
        max_depth: int = 5,
        link_types: Optional[Set[str]] = None,
        artifact_types: Optional[Set[str]] = None,
        project_id: Optional[int] = None,
    ) -> Dict[int, TracePath]:
        """
        Find all artifacts reachable from a starting point.

        Args:
            start_artifact_id: Starting artifact
            direction: Which links to follow
            max_depth: Maximum traversal depth
            link_types: Filter to specific link types
            artifact_types: Filter to specific artifact types
            project_id: Filter to specific project

        Returns:
            Dict mapping artifact_id to shortest TracePath
        """
        reachable: Dict[int, TracePath] = {}

        # BFS
        queue: List[Tuple[int, List[int], List[int], List[str], List[float], int]] = [
            (start_artifact_id, [start_artifact_id], [], [], [], 0)
        ]
        visited = {start_artifact_id}

        while queue:
            current_id, path_ids, link_ids, types, confs, depth = queue.pop(0)

            if depth > max_depth:
                continue

            # Build query based on direction
            if direction == "outgoing":
                stmt = (
                    select(ArtifactLink, Artifact)
                    .join(Artifact, Artifact.id == ArtifactLink.to_artifact_id)
                    .where(ArtifactLink.from_artifact_id == current_id)
                )
            elif direction == "incoming":
                stmt = (
                    select(ArtifactLink, Artifact)
                    .join(Artifact, Artifact.id == ArtifactLink.from_artifact_id)
                    .where(ArtifactLink.to_artifact_id == current_id)
                )
            else:  # both
                stmt = select(ArtifactLink, Artifact).where(
                    or_(
                        and_(
                            ArtifactLink.from_artifact_id == current_id,
                            Artifact.id == ArtifactLink.to_artifact_id,
                        ),
                        and_(
                            ArtifactLink.to_artifact_id == current_id,
                            Artifact.id == ArtifactLink.from_artifact_id,
                        ),
                    )
                )

            if link_types:
                stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
            if artifact_types:
                stmt = stmt.where(Artifact.type.in_(artifact_types))
            if project_id is not None:
                stmt = stmt.where(ArtifactLink.project_id == project_id)

            result = await self.db.execute(stmt)
            rows = result.all()

            for link, artifact in rows:
                # Determine next artifact ID based on direction
                if direction == "outgoing":
                    next_id = link.to_artifact_id
                elif direction == "incoming":
                    next_id = link.from_artifact_id
                else:
                    next_id = (
                        link.to_artifact_id
                        if link.from_artifact_id == current_id
                        else link.from_artifact_id
                    )

                if next_id not in visited:
                    visited.add(next_id)

                    new_path = path_ids + [next_id]
                    new_links = link_ids + [link.id]
                    new_types = types + [link.link_type]
                    normalized_conf = normalize_confidence(link.confidence) or 1.0
                    new_confs = confs + [normalized_conf]

                    total_conf = 1.0
                    for c in new_confs:
                        total_conf *= c

                    path = TracePath(
                        start_artifact_id=start_artifact_id,
                        end_artifact_id=next_id,
                        path=new_path,
                        links=new_links,
                        link_types=new_types,
                        total_confidence=total_conf,
                        min_confidence=min(new_confs),
                        path_length=len(new_path) - 1,
                    )

                    reachable[next_id] = path
                    queue.append((next_id, new_path, new_links, new_types, new_confs, depth + 1))

        return reachable

    # -------------------------------------------------------------------------
    # Derived Link Computation
    # -------------------------------------------------------------------------

    async def compute_derived_links(
        self,
        project_id: int,
        *,
        from_type: str = "requirement",
        to_type: str = "commit",
        via_types: Optional[List[str]] = None,
        max_depth: int = 3,
    ) -> List[DerivedLink]:
        """
        Compute derived links between artifact types.

        For example: requirement → jira_issue → commit
        Creates derived link: requirement → commit (traced_to)

        Args:
            project_id: Project to process
            from_type: Starting artifact type
            to_type: Target artifact type
            via_types: Intermediate artifact types (if None, any)
            max_depth: Maximum path depth

        Returns:
            List of DerivedLink objects
        """
        # Get all artifacts of from_type
        from_stmt = select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.type == from_type,
        )
        from_result = await self.db.execute(from_stmt)
        from_artifacts = from_result.scalars().all()

        # Get all artifacts of to_type
        to_stmt = select(Artifact).where(
            Artifact.project_id == project_id,
            Artifact.type == to_type,
        )
        to_result = await self.db.execute(to_stmt)
        to_artifact_ids = {a.id for a in to_result.scalars().all()}

        derived_links: List[DerivedLink] = []

        for from_artifact in from_artifacts:
            # Find all reachable artifacts
            reachable = await self.find_all_reachable(
                from_artifact.id,
                direction="outgoing",
                max_depth=max_depth,
                project_id=project_id,
            )

            # Filter to target type
            for artifact_id, path in reachable.items():
                if artifact_id in to_artifact_ids:
                    # Create derived link
                    derived = DerivedLink(
                        from_artifact_id=from_artifact.id,
                        to_artifact_id=artifact_id,
                        derived_type=f"{from_type}_to_{to_type}",
                        paths=[path],
                        combined_confidence=path.total_confidence,
                        metadata={
                            "from_type": from_type,
                            "to_type": to_type,
                            "via_types": path.link_types,
                        },
                    )
                    derived_links.append(derived)

        logger.info(
            "Computed %d derived links: %s -> %s for project %d",
            len(derived_links),
            from_type,
            to_type,
            project_id,
        )

        return derived_links

    # -------------------------------------------------------------------------
    # Materialization
    # -------------------------------------------------------------------------

    async def materialize_derived_links(
        self,
        project_id: int,
        derived_links: List[DerivedLink],
        *,
        created_by_id: Optional[int] = None,
        overwrite: bool = False,
    ) -> Tuple[int, int]:
        """
        Materialize derived links to the database.

        Args:
            project_id: Project ID
            derived_links: Links to materialize
            created_by_id: User ID for audit
            overwrite: If True, delete existing derived links first

        Returns:
            Tuple of (created_count, skipped_count)
        """
        if overwrite:
            # Delete existing derived links
            await self.db.execute(
                delete(ArtifactLink).where(
                    ArtifactLink.project_id == project_id,
                    ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
                )
            )

        created = 0
        skipped = 0

        for derived in derived_links:
            # Check if link already exists
            existing = await self.db.execute(
                select(ArtifactLink).where(
                    ArtifactLink.from_artifact_id == derived.from_artifact_id,
                    ArtifactLink.to_artifact_id == derived.to_artifact_id,
                    ArtifactLink.link_type == derived.derived_type,
                )
            )

            if existing.scalar_one_or_none():
                skipped += 1
                continue

            # Create materialized link
            link = ArtifactLink(
                tenant_id=None,  # Inherit from project
                project_id=project_id,
                created_by_id=created_by_id,
                created_via="rule",
                source_system=self.DERIVED_SOURCE_SYSTEM,
                source_reference_id=None,
                method="derivation",
                from_artifact_id=derived.from_artifact_id,
                to_artifact_id=derived.to_artifact_id,
                link_type=derived.derived_type,
                confidence=derived.combined_confidence,
                confidence_factors={
                    "derived": True,
                    "paths": [p.to_dict() for p in derived.paths],
                    "metadata": derived.metadata,
                },
            )

            self.db.add(link)
            created += 1

        await self.db.flush()

        logger.info(
            "Materialized %d derived links (skipped %d existing) for project %d",
            created,
            skipped,
            project_id,
        )

        return created, skipped

    async def invalidate_derived_links(
        self,
        artifact_id: int,
        *,
        project_id: Optional[int] = None,
    ) -> int:
        """
        Invalidate (delete) derived links affected by an artifact change.

        Args:
            artifact_id: Artifact that changed
            project_id: Optional project filter

        Returns:
            Number of deleted links
        """
        # Find all derived links that include this artifact in their path
        stmt = select(ArtifactLink).where(
            ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
            or_(
                ArtifactLink.from_artifact_id == artifact_id,
                ArtifactLink.to_artifact_id == artifact_id,
            ),
        )

        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)

        result = await self.db.execute(stmt)
        links = result.scalars().all()

        # Also find links where artifact is in the path (stored in confidence_factors)
        path_links_stmt = select(ArtifactLink).where(
            ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
            ArtifactLink.confidence_factors.isnot(None),
        )

        if project_id is not None:
            path_links_stmt = path_links_stmt.where(ArtifactLink.project_id == project_id)

        path_result = await self.db.execute(path_links_stmt)
        path_links = path_result.scalars().all()

        to_delete = set()

        # Add directly connected links
        for link in links:
            to_delete.add(link.id)

        # Check path links
        for link in path_links:
            factors = link.confidence_factors or {}
            paths = factors.get("paths", [])

            for path_data in paths:
                if artifact_id in path_data.get("path", []):
                    to_delete.add(link.id)
                    break

        # Delete
        if to_delete:
            await self.db.execute(delete(ArtifactLink).where(ArtifactLink.id.in_(to_delete)))

        logger.info(
            "Invalidated %d derived links for artifact %d",
            len(to_delete),
            artifact_id,
        )

        return len(to_delete)

    # -------------------------------------------------------------------------
    # Transitive Closure
    # -------------------------------------------------------------------------

    async def compute_transitive_closure(
        self,
        project_id: int,
        link_type: str,
        *,
        max_depth: int = 10,
    ) -> List[Tuple[int, int, int]]:
        """
        Compute transitive closure for a link type.

        For example, if A implements B and B implements C,
        then A transitively implements C.

        Args:
            project_id: Project to process
            link_type: Link type to compute closure for
            max_depth: Maximum chain length

        Returns:
            List of (from_id, to_id, depth) tuples
        """
        closure: List[Tuple[int, int, int]] = []

        # Get all direct links
        direct_stmt = select(ArtifactLink).where(
            ArtifactLink.project_id == project_id,
            ArtifactLink.link_type == link_type,
        )
        direct_result = await self.db.execute(direct_stmt)
        direct_links = direct_result.scalars().all()

        # Build adjacency list
        graph: Dict[int, List[int]] = {}
        for link in direct_links:
            if link.from_artifact_id not in graph:
                graph[link.from_artifact_id] = []
            graph[link.from_artifact_id].append(link.to_artifact_id)

        # For each node, find all reachable nodes
        for start_id in graph:
            visited = set()
            queue = [(start_id, 0)]

            while queue:
                current, depth = queue.pop(0)

                if depth > max_depth:
                    continue

                for next_id in graph.get(current, []):
                    if next_id not in visited and next_id != start_id:
                        visited.add(next_id)

                        # Only add transitive (depth > 1) relationships
                        if depth > 0:
                            closure.append((start_id, next_id, depth + 1))

                        queue.append((next_id, depth + 1))

        return closure

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------

    async def get_derivation_stats(
        self,
        project_id: int,
    ) -> Dict[str, Any]:
        """Get statistics about derived links in a project."""
        # Count total derived links
        total_stmt = select(func.count(ArtifactLink.id)).where(
            ArtifactLink.project_id == project_id,
            ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
        )
        total_result = await self.db.execute(total_stmt)
        total = total_result.scalar() or 0

        # Count by derived type
        type_stmt = (
            select(ArtifactLink.link_type, func.count(ArtifactLink.id))
            .where(
                ArtifactLink.project_id == project_id,
                ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
            )
            .group_by(ArtifactLink.link_type)
        )
        type_result = await self.db.execute(type_stmt)
        by_type = {row[0]: row[1] for row in type_result.all()}

        # Average confidence
        conf_stmt = select(func.avg(ArtifactLink.confidence)).where(
            ArtifactLink.project_id == project_id,
            ArtifactLink.source_system == self.DERIVED_SOURCE_SYSTEM,
            ArtifactLink.confidence.isnot(None),
        )
        conf_result = await self.db.execute(conf_stmt)
        avg_confidence = conf_result.scalar() or 0.0

        return {
            "total_derived_links": total,
            "by_type": by_type,
            "average_confidence": float(avg_confidence),
        }


# Factory function for dependency injection
def get_derivation_service(db: AsyncSession) -> DerivationService:
    """Get DerivationService instance."""
    return DerivationService(db)
