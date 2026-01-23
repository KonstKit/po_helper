from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class ConfluencePage(Base):
    __tablename__ = "confluence_pages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    confluence_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    space_key: Mapped[str] = mapped_column(String, index=True)
    title: Mapped[str] = mapped_column(String, index=True)
    page_type: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    labels: Mapped[list[str] | None] = mapped_column(JSON)
    html: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now())
