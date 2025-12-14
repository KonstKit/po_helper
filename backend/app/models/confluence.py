from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base


class ConfluencePage(Base):
    __tablename__ = "confluence_pages"

    id = Column(Integer, primary_key=True, index=True)
    confluence_id = Column(String, unique=True, index=True)
    space_key = Column(String, index=True)
    title = Column(String, index=True)
    page_type = Column(String)
    url = Column(String)
    version = Column(Integer)
    created = Column(DateTime(timezone=True))
    updated = Column(DateTime(timezone=True))
    labels = Column(JSON)
    html = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

