from typing import Optional, List
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_STRONG_ENCRYPTION_SECRET_LENGTH = 32
MIN_STRONG_ENCRYPTION_SECRET_UNIQUE_CHARS = 10
WEAK_ENCRYPTION_SECRET_MARKERS = (
    "change-me",
    "changeme",
    "replace-me",
    "replace_this",
    "placeholder",
    "secret-key-here",
    "change-in-production",
    "generate-another-secret-key-here",
)


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

    DB_POOL_SIZE: int = 3
    DB_POOL_MAX_OVERFLOW: int = 2
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

    BACKEND_BIND_HOST: str = "127.0.0.1"
    ALLOW_UNAUTHENTICATED_DEMO_API: bool = False

    # Encryption
    ENCRYPTION_SECRET: Optional[str] = None  # if not set, falls back to SECRET_KEY
    ENCRYPTION_SECRET_PREVIOUS: List[str] = []

    # Feature flags
    ENABLE_CONFLUENCE_AUTOLINK: bool = False

    # Task queue / async processing
    CELERY_ENABLED: bool = False
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_USE_IN_DEV: bool = False
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = 1

    # Redis cache / broker
    REDIS_URL: str = "redis://localhost:6379/0"

    # Health / alerting thresholds
    ALERT_API_ERROR_WINDOW_SECONDS: int = 300
    ALERT_API_ERROR_THRESHOLD: int = 20
    ALERT_QUEUE_BACKLOG_THRESHOLD: int = 100
    ALERT_SYNC_FAILURE_WINDOW_SECONDS: int = 86400
    ALERT_SYNC_FAILURE_THRESHOLD: int = 5

    # Traceability caching (in-memory, optional)
    ENABLE_MATRIX_CACHE: bool = False
    MATRIX_CACHE_TTL_SECONDS: int = 300
    SYNC_TASK_RUNNING_TTL_SECONDS: int = 7200  # Auto-fail running sync tasks without heartbeat
    SYNC_TASK_ACTIVE_HEARTBEAT_GRACE_SECONDS: int = 900  # Block overlapping sync only when heartbeat is fresh

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

    # Shared integration HTTP defaults (non-Jira clients)
    INTEGRATION_HTTP_TIMEOUT: int = 30
    INTEGRATION_HTTP_MAX_RETRIES: int = 2
    INTEGRATION_HTTP_BACKOFF_SECONDS: float = 1.0
    INTEGRATION_HTTP_BACKOFF_MAX_SECONDS: float = 30.0

    # Pagination settings for Jira API
    JIRA_PAGE_SIZE: int = 50  # Fetch 50 items per request
    JIRA_MAX_RESULTS: int = 500  # Maximum total results to fetch
    JIRA_WORKLOG_MAX_PAGES: int = 2000  # Hard safety cap for worklog pagination loops
    JIRA_SPRINT_ISSUES_MAX_PAGES: int = 500  # Hard safety cap for sprint issues pagination

    # Cache settings for Jira data
    JIRA_CACHE_TTL: int = 300  # Cache TTL in seconds (5 minutes)
    JIRA_CACHE_ENABLED: bool = True  # Enable caching for expensive operations

    # PR metrics aggregation knobs
    PR_METRICS_CACHE_TTL_SECONDS: int = 60
    PR_METRICS_SAMPLE_LIMIT: int = 20

    # Export settings
    EXPORTS_DIR: str = "./exports"  # Directory for export files
    EXPORT_FILE_TTL_HOURS: int = 24  # Auto-delete exports after 24 hours
    BASELINE_RETENTION_DAYS: int = 90  # Auto-delete baselines older than N days

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

    @property
    def has_dedicated_encryption_secret(self) -> bool:
        secret = (self.ENCRYPTION_SECRET or "").strip()
        fallback = (self.SECRET_KEY or "").strip()
        return bool(secret) and secret != fallback

    @property
    def has_strong_encryption_secret(self) -> bool:
        secret = (self.ENCRYPTION_SECRET or "").strip()
        if not secret:
            return False
        if len(secret) < MIN_STRONG_ENCRYPTION_SECRET_LENGTH:
            return False
        if len(set(secret)) < MIN_STRONG_ENCRYPTION_SECRET_UNIQUE_CHARS:
            return False

        lowered = secret.lower()
        return not any(marker in lowered for marker in WEAK_ENCRYPTION_SECRET_MARKERS)

    @property
    def has_strong_dedicated_encryption_secret(self) -> bool:
        return self.has_dedicated_encryption_secret and self.has_strong_encryption_secret

    # Usage analytics
    ANALYTICS_BATCH_MAX_SIZE: int = 500
    ANALYTICS_RETENTION_DAYS: int = 90
    # Cap on the JSON-serialised size of a single event's `eventData`.
    # Protects the persisted event_data column and downstream aggregations
    # from oversized client payloads. 4 KiB is generous for a usage event.
    ANALYTICS_EVENT_DATA_MAX_BYTES: int = 4096
    # How far into the future a client-supplied timestamp may be (seconds).
    # Allows for normal client/server clock skew while rejecting events
    # that would poison time-windowed aggregations (e.g. retention, TTV).
    ANALYTICS_MAX_FUTURE_SKEW_SECONDS: int = 300

    # Traceability transform behavior contract (plan_69).
    # When True (default), an unsupported `transform_type` on a transformNode
    # raises a terminal execution error. Set to False during a rolling
    # deploy where new code may run before Alembic revision
    # 034_rewrite_legacy_transform_types has migrated existing flow_json
    # rows; in that mode an unsupported value emits a warning and passes
    # artifacts through, matching pre-plan_69 behavior. Flip back to True
    # once the migration completes.
    TRACEABILITY_TRANSFORM_STRICT: bool = True

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

    @field_validator("ENCRYPTION_SECRET_PREVIOUS", mode="before")
    @classmethod
    def _normalize_encryption_secret_previous(cls, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, list):
            return [str(part).strip() for part in value if str(part).strip()]
        return []

    @field_validator("ENCRYPTION_SECRET", mode="before")
    @classmethod
    def _normalize_encryption_secret(cls, value: str | None) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("BACKEND_BIND_HOST", mode="before")
    @classmethod
    def _normalize_backend_bind_host(cls, value: str | None) -> str:
        if value is None:
            return "127.0.0.1"
        normalized = value.strip()
        return normalized or "127.0.0.1"


settings = Settings()
