from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class BusinessValueAudit(Base):
    __tablename__ = "business_value_audit"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    old_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_delivered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    new_delivered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    old_roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_roi: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
