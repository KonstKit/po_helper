from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class IntegrationSetting(Base):
    __tablename__ = "integration_settings"

    id = Column(Integer, primary_key=True, index=True)
    kind = Column(String, index=True, nullable=False)  # 'jira' | 'confluence'
    base_url = Column(String, nullable=True)
    email = Column(String, nullable=True)
    api_token = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

