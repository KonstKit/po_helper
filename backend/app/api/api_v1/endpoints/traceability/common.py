"""Common imports, utilities, and helper functions for traceability endpoints."""

from __future__ import annotations

import logging
from typing import Optional, Set

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import ArtifactLink
from app.utils.batch_operations import (
    detect_cycles_batched,
)

logger = logging.getLogger(__name__)


def _dag_types() -> Set[str]:
    """Return the set of DAG-enforced link types."""
    return {"implements", "tests", "deploys", "derives_from"}


async def _would_create_cycle(
    db: AsyncSession,
    from_id: int,
    to_id: int,
    link_type: str,
    project_id: Optional[int] = None,
) -> bool:
    """Detect cycle for DAG-enforced link types using batched BFS.

    Uses O(depth) queries instead of O(vertices) by batching all nodes per level.
    """
    if link_type not in _dag_types():
        return False

    return await detect_cycles_batched(
        db=db,
        link_model=ArtifactLink,
        from_column="from_artifact_id",
        to_column="to_artifact_id",
        start_id=from_id,
        target_id=to_id,
        project_id=project_id,
        max_depth=10,
    )


async def _link_exists(
    db: AsyncSession,
    from_id: int,
    to_id: int,
    link_type: str,
) -> Optional[ArtifactLink]:
    """Check if a link already exists between two artifacts."""
    res = await db.execute(
        select(ArtifactLink).where(
            ArtifactLink.from_artifact_id == from_id,
            ArtifactLink.to_artifact_id == to_id,
            ArtifactLink.link_type == link_type,
        )
    )
    return res.scalar_one_or_none()
