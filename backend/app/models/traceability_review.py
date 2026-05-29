from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

# Lifecycle status graph (plan_70):
#   pending -> claimed -> resolved | rejected
#   resolved | rejected -> pending (reopen, privileged actor only)
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_CLAIMED = "claimed"
REVIEW_STATUS_RESOLVED = "resolved"
REVIEW_STATUS_REJECTED = "rejected"

REVIEW_STATUSES = (
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CLAIMED,
    REVIEW_STATUS_RESOLVED,
    REVIEW_STATUS_REJECTED,
)

# An item still occupying the active queue (deduplication scope).
OPEN_REVIEW_STATUSES = (REVIEW_STATUS_PENDING, REVIEW_STATUS_CLAIMED)
TERMINAL_REVIEW_STATUSES = (REVIEW_STATUS_RESOLVED, REVIEW_STATUS_REJECTED)

REVIEW_PRIORITIES = ("low", "normal", "high", "urgent")


class TraceabilityReviewItem(Base):
    """Durable manual-review work item produced by traceability rule execution.

    The ``queueReviewAction`` rule node used to emit transient execution
    warnings. Those warnings are now persisted as review items so operators
    have a durable, auditable queue of low-confidence / ambiguous artifacts to
    triage. See ``plan_70`` and ``docs/TRACEABILITY_REVIEW_QUEUE.md``.
    """

    __tablename__ = "traceability_review_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), index=True, nullable=True
    )
    artifact_id: Mapped[int] = mapped_column(
        ForeignKey("artifacts.id"), nullable=False, index=True
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("traceability_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    rule_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("traceability_rule_executions.id", ondelete="SET NULL"), nullable=True
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=REVIEW_STATUS_PENDING
    )
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NOTE: ``metadata`` is reserved by SQLAlchemy's declarative Base, so the
    # Python attribute is ``meta`` while the DB column keeps the contract name.
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        # Deduplication: at most one *open* review item per
        # (project, artifact, rule, node). Terminal items are excluded so a
        # reopened/rerun cycle can create a fresh item.
        Index(
            "uq_traceability_review_items_open",
            "project_id",
            "artifact_id",
            "rule_id",
            "node_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'claimed')"),
            postgresql_where=text("status IN ('pending', 'claimed')"),
        ),
        Index(
            "ix_traceability_review_items_status_project",
            "project_id",
            "status",
            "priority",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TraceabilityReviewItem(id={self.id}, artifact_id={self.artifact_id}, "
            f"status='{self.status}', priority='{self.priority}')>"
        )
