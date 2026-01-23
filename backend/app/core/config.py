from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PO Helper"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    SECRET_KEY: str = Field(default="your-secret-key-here-change-in-production", min_length=32)
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ENVIRONMENT: str = Field(default="development", alias="ENVIRONMENT")

    # Database URL - reads from environment, defaults to SQLite for local dev
    # Note: Default is computed at module load time for compatibility with all call sites
    DATABASE_URL: str = "sqlite+aiosqlite:///./po_helper.db"

    @property
    def effective_database_url(self) -> str:
        """Return DATABASE_URL, with fallback to SQLite if empty/None."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        # Fallback to SQLite for local development (shouldn't reach here with default set)
        return "sqlite+aiosqlite:///./po_helper.db"

    DB_POOL_SIZE: int = 5
    DB_POOL_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True

    JIRA_BASE_URL: Optional[str] = None
    JIRA_EMAIL: Optional[str] = None
    JIRA_API_TOKEN: Optional[str] = None

    CONFLUENCE_BASE_URL: Optional[str] = None
    CONFLUENCE_EMAIL: Optional[str] = None
    CONFLUENCE_API_TOKEN: Optional[str] = None

    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8001",
    ]

    # Encryption
    ENCRYPTION_SECRET: Optional[str] = None  # if not set, falls back to SECRET_KEY

    # Feature flags
    ENABLE_CONFLUENCE_AUTOLINK: bool = False

    # Task queue / async processing
    CELERY_ENABLED: bool = False
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_USE_IN_DEV: bool = False

    # Redis cache / broker
    REDIS_URL: str = "redis://localhost:6379/0"

    # Traceability caching (in-memory, optional)
    ENABLE_MATRIX_CACHE: bool = False
    MATRIX_CACHE_TTL_SECONDS: int = 300

    # Webhook secrets
    GITHUB_WEBHOOK_SECRET: Optional[str] = None
    GITLAB_WEBHOOK_SECRET: Optional[str] = None
    BITBUCKET_WEBHOOK_SECRET: Optional[str] = None
    GITHUB_API_TOKEN: Optional[str] = None  # for setting commit statuses

    # Jira integration knobs
    JIRA_FORCE_PAT: bool = False  # Force PAT (Bearer) mode even if email provided
    JIRA_DISABLE_DISCOVERY: bool = False  # Skip baseUrl discovery adjustments
    # HTTP client behavior for Jira
    JIRA_HTTP_TIMEOUT: int = 25  # seconds (reduced from 60 to fail faster)
    JIRA_WORKLOG_TIMEOUT: int = 30  # seconds for worklog endpoints (reduced from 120)
    JIRA_HTTP_MAX_RETRIES: int = 2  # number of retries on timeouts
    JIRA_HTTP_BACKOFF_SECONDS: float = 1.0  # base backoff seconds (exponential)
    # Optional circuit breaker to avoid request loops when Jira is misbehaving
    JIRA_CB_ENABLED: bool = True  # Enable circuit breaker
    JIRA_CB_THRESHOLD: int = 3  # Open circuit after 3 failures
    JIRA_CB_SLEEP_SECONDS: int = 30  # Wait 30 seconds before retrying

    # Pagination settings for Jira API
    JIRA_PAGE_SIZE: int = 50  # Fetch 50 items per request
    JIRA_MAX_RESULTS: int = 500  # Maximum total results to fetch

    # Cache settings for Jira data
    JIRA_CACHE_TTL: int = 300  # Cache TTL in seconds (5 minutes)
    JIRA_CACHE_ENABLED: bool = True  # Enable caching for expensive operations

    # PR metrics aggregation knobs
    PR_METRICS_CACHE_TTL_SECONDS: int = 60
    PR_METRICS_SAMPLE_LIMIT: int = 20

    # WIP limits (simple per-assignee)
    WIP_LIMIT_PER_ASSIGNEE: int = 2
    # Optional per-assignee overrides: { "email": 3, ... }
    WIP_LIMIT_OVERRIDES: dict[str, int] = {}

    # Sprint capacity baseline (hours per week per developer)
    CAPACITY_HOURS_PER_WEEK: int = 30

    # Debug/Diagnostics
    DEBUG: bool = False
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.0

    # OAuth2 SSO Configuration
    OAUTH_ENABLED: bool = False  # Master switch for OAuth2 SSO

    # Google OAuth2
    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/google/callback"

    # Microsoft OAuth2 (Azure AD)
    MICROSOFT_CLIENT_ID: Optional[str] = None
    MICROSOFT_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_TENANT_ID: str = "common"  # 'common' for multi-tenant, or specific tenant ID
    MICROSOFT_REDIRECT_URI: str = "http://localhost:8000/api/v1/oauth/microsoft/callback"

    # OAuth behavior
    OAUTH_AUTO_CREATE_USERS: bool = True  # Auto-create users on first OAuth login
    OAUTH_ALLOWED_DOMAINS: List[str] = []  # Empty = all domains allowed

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    @property
    def microsoft_oauth_configured(self) -> bool:
        return bool(self.MICROSOFT_CLIENT_ID and self.MICROSOFT_CLIENT_SECRET)

    # Service auto-connection control
    SKIP_SERVICE_AUTOCONNECT: bool = False

    # Jira status mapping to normalize different workflows
    # Used by analytics to decide what is done vs active
    JIRA_STATUS_MAPPING: dict = {
        "todo": ["To Do", "Open", "Backlog", "New"],
        "in_progress": ["In Progress", "In Development", "Active"],
        "done": ["Done", "Closed", "Resolved", "Complete"],
    }

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _normalize_environment(cls, value: str | None) -> str:
        if value is None:
            return "development"
        normalized = str(value).strip().lower()
        mapping = {
            "development": "development",
            "dev": "development",
            "staging": "staging",
            "production": "production",
            "prod": "production",
            "test": "test",
        }
        if normalized not in mapping:
            raise ValueError("ENVIRONMENT must be one of development, staging, production, or test")
        return mapping[normalized]

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def _validate_secret_key(cls, value: str | None) -> str:
        if value is None:
            return "your-secret-key-here-change-in-production"
        normalized = value.strip()
        if not normalized:
            raise ValueError("SECRET_KEY cannot be blank.")
        if len(normalized) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long.")
        return normalized


settings = Settings()
