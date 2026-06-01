"""Link Service for managing traceability links with provenance tracking.

This service provides:
- Full CRUD operations for ArtifactLinks
- Provenance tracking (created_via, method, source_system)
- Audit logging for all changes
- Confidence score calculation
- Bidirectional link management
- Batch operations support
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_, select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.request_context import get_request_id
from app.models.traceability import Artifact, ArtifactLink, AuditLog
from app.services.confidence_scoring import confidence_scoring_service
from app.utils.confidence import normalize_confidence, confidence_filter

logger = logging.getLogger(__name__)


class LinkCreationMethod(str, Enum):
    """How the link was created."""

    MANUAL = "manual"
    RULE = "rule"
    SYNC = "sync"
    AUTOLINK = "autolink"
    IMPORT = "import"


class LinkType(str, Enum):
    """Standard link types with semantic meaning."""

    IMPLEMENTS = "implements"
    TESTS = "tests"
    VERIFIES = "verifies"
    DEPLOYS = "deploys"
    DERIVES_FROM = "derives_from"
    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    CHILD_OF = "child_of"
    PARENT_OF = "parent_of"
    DOCUMENTS = "documents"


# Link types that enforce DAG (no cycles allowed)
DAG_LINK_TYPES = {
    LinkType.IMPLEMENTS,
    LinkType.TESTS,
    LinkType.DEPLOYS,
    LinkType.DERIVES_FROM,
}

# Reverse link type mapping for bidirectional links
REVERSE_LINK_TYPES = {
    "implements": "implemented_by",
    "implemented_by": "implements",
    "tests": "tested_by",
    "tested_by": "tests",
    "verifies": "verified_by",
    "verified_by": "verifies",
    "deploys": "deployed_by",
    "deployed_by": "deploys",
    "derives_from": "derived_to",
    "derived_to": "derives_from",
    "blocks": "blocked_by",
    "blocked_by": "blocks",
    "child_of": "parent_of",
    "parent_of": "child_of",
    "documents": "documented_by",
    "documented_by": "documents",
}


class LinkService:
    """Service for managing artifact links with full provenance tracking."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # CREATE operations
    # -------------------------------------------------------------------------

    async def create_link(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        link_type: str,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[int] = None,
        created_by_id: Optional[int] = None,
        created_via: str = LinkCreationMethod.MANUAL,
        source_system: Optional[str] = None,
        source_reference_id: Optional[str] = None,
        method: Optional[str] = None,
        confidence: Optional[float] = None,
        confidence_factors: Optional[Dict[str, Any]] = None,
        calculate_confidence: bool = True,
        create_audit: bool = True,
    ) -> ArtifactLink:
        """
        Create a new artifact link with provenance tracking.

        Args:
            from_artifact_id: Source artifact ID
            to_artifact_id: Target artifact ID
            link_type: Type of relationship (implements, tests, etc.)
            tenant_id: Tenant identifier
            project_id: Project ID
            created_by_id: User ID who created the link
            created_via: Creation method (manual, rule, sync, etc.)
            source_system: External system that provided the link
            source_reference_id: Reference ID in external system
            method: Specific method used (e.g., "jira_key_extraction")
            confidence: Confidence score (0.0-1.0), auto-calculated if None
            confidence_factors: Breakdown of confidence factors
            calculate_confidence: Whether to auto-calculate confidence
            create_audit: Whether to create audit log entry

        Returns:
            Created ArtifactLink

        Raises:
            ValueError: If validation fails, the link would create a cycle, or a
                matching link already exists.

        Project scoping:
            When ``project_id`` is not supplied the link is stored under
            ``project_id or from_artifact.project_id`` — i.e. it falls back to
            the source artifact's project. This is a deliberate behavioural
            change: a caller that omitted ``project_id`` previously got a link
            with a NULL ``project_id``; it now gets one scoped to the source
            artifact, which aligns this service with the rule engine
            (``source.project_id or target.project_id``). The ``or`` treats a
            falsy ``project_id`` (None or 0) as "not supplied"; artifact/project
            ids are >= 1, so 0 never occurs in practice. The same resolved value
            is used for both the dedup check and the stored row.

        Idempotency (sequential only):
            Before inserting, an existence check scoped to the full uniqueness
            tuple (tenant_id, project_id, from_artifact_id, to_artifact_id,
            link_type) is run; if a match is found this raises
            ``ValueError("Link already exists: ...")`` rather than inserting a
            second row. This closes the *sequential* duplicate path (a caller
            invoking twice, retry, or at-least-once redelivery) for ALL tenants
            — including single-tenant/local installs where ``tenant_id`` is NULL
            and the ``uq_artifact_link`` unique constraint does NOT dedupe (under
            SQL NULL semantics a NULL ``tenant_id`` does not collide).

            It is NOT a guard against truly *concurrent* inserts: the check is
            read-then-write, so two parallel transactions can both pass the
            SELECT and both INSERT. The ``IntegrityError`` fallback below catches
            that race only when ``tenant_id`` is set (the constraint fires); for
            the NULL-tenant case the constraint does not fire, so a concurrent
            duplicate is still possible (e.g. two workers on Postgres; SQLite
            serialises writes, so it is not exposed there). Closing that fully
            would require a DB-level unique index treating NULL tenant/project as
            sentinels (COALESCE) — intentionally out of scope here.

            Like the rule engine's ``createLinkAction._create_link`` existence
            check this prevents duplicates, but the dedup *granularity* differs:
            the engine matches on (from, to, link_type) only, whereas this
            matches the full (tenant_id, project_id, from, to, link_type) tuple.
            The two coincide on single-tenant data; in a multi-tenant DB this
            method correctly treats the same (from, to, type) under different
            tenant/project as distinct, while the engine would collapse them.

            We raise (rather than return the existing link) to keep the contract
            identical to the pre-existing ``IntegrityError`` path, so
            ``create_links_batch``'s "already exists" skip logic keeps working
            unchanged.
        """
        # Validate artifacts exist
        from_artifact, to_artifact = await self._validate_artifacts(
            from_artifact_id, to_artifact_id
        )

        # Resolve the project the link is stored under (see "Project scoping" in
        # the docstring): an omitted/falsy project_id falls back to the source
        # artifact's project. The same expression builds the stored row below, so
        # the dedup check matches the uq_artifact_link tuple exactly.
        effective_project_id = project_id or from_artifact.project_id

        # Sequential-dedup guard — see "Idempotency (sequential only)" in the
        # docstring. uq_artifact_link does not dedupe NULL-tenant rows, so this
        # explicit existence check covers the retry/redelivery case for every
        # tenant. It is read-then-write, so it does not by itself stop a truly
        # concurrent NULL-tenant insert (the IntegrityError backstop only fires
        # when tenant_id is set). Use .first() (not scalar_one_or_none) so a
        # pre-existing duplicate from an earlier unguarded insert does not itself
        # raise MultipleResultsFound.
        existing_result = await self.db.execute(
            select(ArtifactLink)
            .where(
                ArtifactLink.tenant_id == tenant_id,
                ArtifactLink.project_id == effective_project_id,
                ArtifactLink.from_artifact_id == from_artifact_id,
                ArtifactLink.to_artifact_id == to_artifact_id,
                ArtifactLink.link_type == link_type,
            )
            .limit(1)
        )
        if existing_result.scalars().first() is not None:
            raise ValueError(
                f"Link already exists: {from_artifact_id} -[{link_type}]-> {to_artifact_id}"
            )

        # Check for cycles in DAG link types
        if link_type in [lt.value for lt in DAG_LINK_TYPES]:
            if await self._would_create_cycle(from_artifact_id, to_artifact_id, link_type):
                raise ValueError(f"Link would create a cycle in DAG for type '{link_type}'")

        # Calculate confidence if needed
        if calculate_confidence and confidence is None:
            confidence, confidence_factors = await self._calculate_link_confidence(
                from_artifact, to_artifact, link_type
            )

        # Normalize confidence to 0..1 scale before storing
        normalized_confidence = normalize_confidence(confidence)

        # Create link
        link = ArtifactLink(
            tenant_id=tenant_id,
            project_id=effective_project_id,
            created_by_id=created_by_id,
            created_via=created_via,
            source_system=source_system,
            source_reference_id=source_reference_id,
            method=method,
            from_artifact_id=from_artifact_id,
            to_artifact_id=to_artifact_id,
            link_type=link_type,
            confidence=normalized_confidence,
            confidence_factors=confidence_factors,
        )

        self.db.add(link)

        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise ValueError(
                f"Link already exists: {from_artifact_id} -[{link_type}]-> {to_artifact_id}"
            )

        # Create audit log
        if create_audit and created_by_id:
            await self._create_audit_log(
                actor_id=created_by_id,
                action="create",
                entity_type="artifact_link",
                entity_id=link.id,
                payload={
                    "from_artifact_id": from_artifact_id,
                    "to_artifact_id": to_artifact_id,
                    "link_type": link_type,
                    "created_via": created_via,
                    "confidence": normalized_confidence,
                },
                tenant_id=tenant_id,
                project_id=link.project_id,
            )

        logger.info(
            "Created link: %s -[%s]-> %s (confidence: %.2f)",
            from_artifact.external_id,
            link_type,
            to_artifact.external_id,
            normalized_confidence or 0,
        )

        # Invalidate derived links affected by this new link
        await self._invalidate_derived_links(from_artifact_id, project_id=link.project_id)
        await self._invalidate_derived_links(to_artifact_id, project_id=link.project_id)

        return link

    async def create_links_batch(
        self,
        links_data: List[Dict[str, Any]],
        *,
        created_by_id: Optional[int] = None,
        created_via: str = LinkCreationMethod.RULE,
        skip_duplicates: bool = True,
    ) -> Tuple[List[ArtifactLink], List[Dict[str, Any]]]:
        """
        Create multiple links in batch with error handling.

        Args:
            links_data: List of link specifications
            created_by_id: User ID who created the links
            created_via: Creation method
            skip_duplicates: If True, skip existing links; if False, raise error

        Returns:
            Tuple of (created_links, errors)

        Note:
            Deduplication is inherited from ``create_link``: its tenant-agnostic
            existence check raises ``ValueError("Link already exists: ...")``,
            which is caught below. Because ``create_link`` flushes each row
            before returning, a duplicate appearing twice *within the same
            batch* is also caught (the second spec's existence query sees the
            first spec's flushed row). No separate guard is needed here.
        """
        created = []
        errors = []

        for link_spec in links_data:
            try:
                link = await self.create_link(
                    from_artifact_id=link_spec["from_artifact_id"],
                    to_artifact_id=link_spec["to_artifact_id"],
                    link_type=link_spec["link_type"],
                    tenant_id=link_spec.get("tenant_id"),
                    project_id=link_spec.get("project_id"),
                    created_by_id=created_by_id,
                    created_via=created_via,
                    confidence=link_spec.get("confidence"),
                    confidence_factors=link_spec.get("confidence_factors"),
                    create_audit=False,  # Batch audit at the end
                )
                created.append(link)
            except ValueError as e:
                if "already exists" in str(e) and skip_duplicates:
                    continue
                errors.append({"link_spec": link_spec, "error": str(e)})
            except Exception as e:
                errors.append({"link_spec": link_spec, "error": str(e)})

        # Batch audit
        if created and created_by_id:
            await self._create_audit_log(
                actor_id=created_by_id,
                action="batch_create",
                entity_type="artifact_link",
                entity_id=0,  # Batch operation
                payload={
                    "count": len(created),
                    "link_ids": [link_item.id for link_item in created],
                    "project_ids": sorted(
                        {link_item.project_id for link_item in created if link_item.project_id}
                    ),
                    "created_via": created_via,
                },
            )

        return created, errors

    async def create_bidirectional_link(
        self,
        artifact_a_id: int,
        artifact_b_id: int,
        link_type: str,
        **kwargs,
    ) -> Tuple[ArtifactLink, ArtifactLink]:
        """
        Create bidirectional link (A->B and B->A with reverse type).

        Args:
            artifact_a_id: First artifact ID
            artifact_b_id: Second artifact ID
            link_type: Link type from A to B
            **kwargs: Additional arguments for create_link

        Returns:
            Tuple of (forward_link, reverse_link)
        """
        reverse_type = REVERSE_LINK_TYPES.get(link_type, f"reverse_{link_type}")

        forward = await self.create_link(
            from_artifact_id=artifact_a_id,
            to_artifact_id=artifact_b_id,
            link_type=link_type,
            **kwargs,
        )

        reverse = await self.create_link(
            from_artifact_id=artifact_b_id,
            to_artifact_id=artifact_a_id,
            link_type=reverse_type,
            **kwargs,
        )

        return forward, reverse

    # -------------------------------------------------------------------------
    # READ operations
    # -------------------------------------------------------------------------

    async def get_link(self, link_id: int) -> Optional[ArtifactLink]:
        """Get link by ID."""
        result = await self.db.execute(select(ArtifactLink).where(ArtifactLink.id == link_id))
        return result.scalar_one_or_none()

    async def get_link_by_artifacts(
        self,
        from_artifact_id: int,
        to_artifact_id: int,
        link_type: str,
    ) -> Optional[ArtifactLink]:
        """Get link by artifact IDs and type."""
        result = await self.db.execute(
            select(ArtifactLink).where(
                ArtifactLink.from_artifact_id == from_artifact_id,
                ArtifactLink.to_artifact_id == to_artifact_id,
                ArtifactLink.link_type == link_type,
            )
        )
        return result.scalar_one_or_none()

    async def get_outgoing_links(
        self,
        artifact_id: int,
        *,
        link_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> List[ArtifactLink]:
        """Get all outgoing links from an artifact."""
        stmt = select(ArtifactLink).where(ArtifactLink.from_artifact_id == artifact_id)

        if link_types:
            stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
        if min_confidence is not None:
            stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))
        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_incoming_links(
        self,
        artifact_id: int,
        *,
        link_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> List[ArtifactLink]:
        """Get all incoming links to an artifact."""
        stmt = select(ArtifactLink).where(ArtifactLink.to_artifact_id == artifact_id)

        if link_types:
            stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
        if min_confidence is not None:
            stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))
        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_links_for_artifact(
        self,
        artifact_id: int,
        *,
        direction: str = "both",  # "outgoing", "incoming", "both"
        link_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        project_id: Optional[int] = None,
    ) -> Dict[str, List[ArtifactLink]]:
        """Get all links for an artifact (incoming and/or outgoing)."""
        result: Dict[str, List[ArtifactLink]] = {"outgoing": [], "incoming": []}

        if direction in ("outgoing", "both"):
            result["outgoing"] = await self.get_outgoing_links(
                artifact_id,
                link_types=link_types,
                min_confidence=min_confidence,
                project_id=project_id,
            )

        if direction in ("incoming", "both"):
            result["incoming"] = await self.get_incoming_links(
                artifact_id,
                link_types=link_types,
                min_confidence=min_confidence,
                project_id=project_id,
            )

        return result

    async def get_links_by_project(
        self,
        project_id: int,
        *,
        link_types: Optional[List[str]] = None,
        min_confidence: Optional[float] = None,
        offset: int = 0,
        limit: int = 1000,
    ) -> List[ArtifactLink]:
        """Get all links for a project."""
        stmt = select(ArtifactLink).where(ArtifactLink.project_id == project_id)

        if link_types:
            stmt = stmt.where(ArtifactLink.link_type.in_(link_types))
        if min_confidence is not None:
            stmt = stmt.where(confidence_filter(ArtifactLink.confidence, min_confidence))

        stmt = stmt.offset(offset).limit(limit)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def count_links(
        self,
        *,
        project_id: Optional[int] = None,
        link_type: Optional[str] = None,
        created_via: Optional[str] = None,
    ) -> int:
        """Count links matching criteria."""
        stmt = select(func.count(ArtifactLink.id))

        if project_id is not None:
            stmt = stmt.where(ArtifactLink.project_id == project_id)
        if link_type is not None:
            stmt = stmt.where(ArtifactLink.link_type == link_type)
        if created_via is not None:
            stmt = stmt.where(ArtifactLink.created_via == created_via)

        result = await self.db.execute(stmt)
        return result.scalar() or 0

    # -------------------------------------------------------------------------
    # UPDATE operations
    # -------------------------------------------------------------------------

    async def update_link(
        self,
        link_id: int,
        *,
        confidence: Optional[float] = None,
        confidence_factors: Optional[Dict[str, Any]] = None,
        updated_by_id: Optional[int] = None,
        create_audit: bool = True,
    ) -> Optional[ArtifactLink]:
        """Update link confidence or other mutable fields."""
        link = await self.get_link(link_id)
        if not link:
            return None

        old_confidence = link.confidence
        changes = {}

        if confidence is not None:
            normalized_conf = normalize_confidence(confidence)
            link.confidence = normalized_conf
            changes["confidence"] = {"old": old_confidence, "new": normalized_conf}

        if confidence_factors is not None:
            link.confidence_factors = confidence_factors
            changes["confidence_factors"] = confidence_factors

        await self.db.flush()

        if create_audit and updated_by_id and changes:
            await self._create_audit_log(
                actor_id=updated_by_id,
                action="update",
                entity_type="artifact_link",
                entity_id=link_id,
                payload=changes,
                tenant_id=link.tenant_id,
                project_id=link.project_id,
            )

        # Invalidate derived links if confidence changed
        if changes:
            await self._invalidate_derived_links(link.from_artifact_id, project_id=link.project_id)
            await self._invalidate_derived_links(link.to_artifact_id, project_id=link.project_id)

        return link

    async def recalculate_confidence(
        self,
        link_id: int,
        *,
        updated_by_id: Optional[int] = None,
    ) -> Optional[ArtifactLink]:
        """Recalculate confidence score for an existing link."""
        link = await self.get_link(link_id)
        if not link:
            return None

        # Fetch artifacts
        from_result = await self.db.execute(
            select(Artifact).where(Artifact.id == link.from_artifact_id)
        )
        to_result = await self.db.execute(
            select(Artifact).where(Artifact.id == link.to_artifact_id)
        )

        from_artifact = from_result.scalar_one_or_none()
        to_artifact = to_result.scalar_one_or_none()

        if not from_artifact or not to_artifact:
            return link

        new_confidence, new_factors = await self._calculate_link_confidence(
            from_artifact, to_artifact, link.link_type
        )

        return await self.update_link(
            link_id,
            confidence=new_confidence,
            confidence_factors=new_factors,
            updated_by_id=updated_by_id,
        )

    # -------------------------------------------------------------------------
    # DELETE operations
    # -------------------------------------------------------------------------

    async def delete_link(
        self,
        link_id: int,
        *,
        deleted_by_id: Optional[int] = None,
        create_audit: bool = True,
    ) -> bool:
        """Delete a link with audit logging."""
        link = await self.get_link(link_id)
        if not link:
            return False

        # Capture info for audit before deletion
        link_info: Dict[str, Any] = {
            "from_artifact_id": link.from_artifact_id,
            "to_artifact_id": link.to_artifact_id,
            "link_type": link.link_type,
            "confidence": link.confidence,
            "created_via": link.created_via,
        }

        await self.db.delete(link)
        await self.db.flush()

        if create_audit and deleted_by_id:
            await self._create_audit_log(
                actor_id=deleted_by_id,
                action="delete",
                entity_type="artifact_link",
                entity_id=link_id,
                payload=link_info,
                tenant_id=link.tenant_id,
                project_id=link.project_id,
            )

        # Invalidate derived links affected by this deletion
        await self._invalidate_derived_links(
            link_info["from_artifact_id"], project_id=link.project_id
        )
        await self._invalidate_derived_links(
            link_info["to_artifact_id"], project_id=link.project_id
        )

        logger.info("Deleted link %d: %s", link_id, link_info)
        return True

    async def delete_links_for_artifact(
        self,
        artifact_id: int,
        *,
        direction: str = "both",  # "outgoing", "incoming", "both"
        deleted_by_id: Optional[int] = None,
    ) -> int:
        """Delete all links for an artifact."""
        project_id = None
        if deleted_by_id:
            result = await self.db.execute(
                select(Artifact.project_id).where(Artifact.id == artifact_id)
            )
            project_id = result.scalar_one_or_none()

        conditions = []

        if direction in ("outgoing", "both"):
            conditions.append(ArtifactLink.from_artifact_id == artifact_id)
        if direction in ("incoming", "both"):
            conditions.append(ArtifactLink.to_artifact_id == artifact_id)

        if not conditions:
            return 0

        # Count for return
        count_stmt = select(func.count(ArtifactLink.id)).where(or_(*conditions))
        count_result = await self.db.execute(count_stmt)
        count = count_result.scalar() or 0

        # Delete
        delete_stmt = delete(ArtifactLink).where(or_(*conditions))
        await self.db.execute(delete_stmt)

        if deleted_by_id and count > 0:
            await self._create_audit_log(
                actor_id=deleted_by_id,
                action="batch_delete",
                entity_type="artifact_link",
                entity_id=artifact_id,
                payload={"artifact_id": artifact_id, "direction": direction, "count": count},
                project_id=project_id,
            )

        # Invalidate derived links for the affected artifact
        if count > 0:
            await self._invalidate_derived_links(artifact_id)

        return count

    # -------------------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------------------

    async def _validate_artifacts(
        self,
        from_id: int,
        to_id: int,
    ) -> Tuple[Artifact, Artifact]:
        """Validate that both artifacts exist."""
        if from_id == to_id:
            raise ValueError("Cannot create self-referencing link")

        result = await self.db.execute(select(Artifact).where(Artifact.id.in_([from_id, to_id])))
        artifacts = {a.id: a for a in result.scalars().all()}

        if from_id not in artifacts:
            raise ValueError(f"Source artifact {from_id} not found")
        if to_id not in artifacts:
            raise ValueError(f"Target artifact {to_id} not found")

        return artifacts[from_id], artifacts[to_id]

    async def _would_create_cycle(
        self,
        from_id: int,
        to_id: int,
        link_type: str,
    ) -> bool:
        """Check if creating this link would create a cycle (BFS from to_id to from_id)."""
        visited = set()
        queue = [to_id]

        while queue:
            current = queue.pop(0)
            if current == from_id:
                return True

            if current in visited:
                continue
            visited.add(current)

            # Get outgoing links of same type
            result = await self.db.execute(
                select(ArtifactLink.to_artifact_id).where(
                    ArtifactLink.from_artifact_id == current,
                    ArtifactLink.link_type == link_type,
                )
            )

            for (next_id,) in result.all():
                if next_id not in visited:
                    queue.append(next_id)

        return False

    async def _calculate_link_confidence(
        self,
        from_artifact: Artifact,
        to_artifact: Artifact,
        link_type: str,
    ) -> Tuple[float, Dict[str, Any]]:
        """Calculate confidence score using ConfidenceScoringService."""
        from_dict = {
            "id": from_artifact.id,
            "type": from_artifact.type,
            "source": from_artifact.source,
            "external_id": from_artifact.external_id,
            "display_key": from_artifact.display_key,
            "title": from_artifact.title,
            "status": from_artifact.status,
            "meta": from_artifact.meta,
            "created_at": from_artifact.created_at,
        }

        to_dict = {
            "id": to_artifact.id,
            "type": to_artifact.type,
            "source": to_artifact.source,
            "external_id": to_artifact.external_id,
            "display_key": to_artifact.display_key,
            "title": to_artifact.title,
            "status": to_artifact.status,
            "meta": to_artifact.meta,
            "created_at": to_artifact.created_at,
        }

        return confidence_scoring_service.calculate_confidence(from_dict, to_dict, link_type)

    async def _create_audit_log(
        self,
        actor_id: int,
        action: str,
        entity_type: str,
        entity_id: int,
        payload: Dict[str, Any],
        tenant_id: Optional[str] = None,
        project_id: Optional[int] = None,
        outcome: str = "success",
    ) -> None:
        """Create audit log entry."""
        audit = AuditLog(
            tenant_id=tenant_id,
            project_id=project_id,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            request_id=get_request_id(),
            outcome=outcome,
            payload=payload,
        )
        self.db.add(audit)
        await self.db.flush()

    async def _invalidate_derived_links(
        self,
        artifact_id: int,
        project_id: Optional[int] = None,
    ) -> int:
        """Invalidate derived links affected by artifact changes.

        Called after link CRUD operations to ensure materialized derived
        links stay consistent.
        """
        # Import locally to avoid circular imports
        from app.services.traceability.derivation_service import DerivationService

        try:
            derivation_service = DerivationService(self.db)
            deleted = await derivation_service.invalidate_derived_links(
                artifact_id, project_id=project_id
            )
            if deleted > 0:
                logger.info(
                    "Invalidated %d derived links for artifact %d",
                    deleted,
                    artifact_id,
                )
            return deleted
        except Exception as e:
            logger.warning(
                "Failed to invalidate derived links for artifact %d: %s",
                artifact_id,
                e,
            )
            return 0


# Factory function for dependency injection
def get_link_service(db: AsyncSession) -> LinkService:
    """Get LinkService instance."""
    return LinkService(db)
