from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PO Helper"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    
    SECRET_KEY: str = "your-secret-key-here-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # SQLite database
    DATABASE_URL: str = "sqlite+aiosqlite:///./po_helper.db"
    
    JIRA_BASE_URL: Optional[str] = None
    JIRA_EMAIL: Optional[str] = None
    JIRA_API_TOKEN: Optional[str] = None
    
    CONFLUENCE_BASE_URL: Optional[str] = None
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None
    
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8000"]
    
    model_config = SettingsConfigDict(env_file='.env', case_sensitive=True)


settings = Settings()