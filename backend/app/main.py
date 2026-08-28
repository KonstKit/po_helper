import logging
import os
import json
import sys
import ipaddress
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import urlparse

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sqlalchemy import select, text

from app.api.api_v1.api import api_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.middleware import register_middlewares
from app.models import Role, SYSTEM_ROLES
from app.models.settings import IntegrationSetting
from app.services.confluence_service import confluence_service
from app.services.integration_secrets import load_integration_token
from app.services.jira_service import jira_service

try:
    from sentry_sdk.integrations.celery import CeleryIntegration
except ImportError:  # pragma: no cover - Celery optional
    CeleryIntegration = None  # type: ignore[assignment, misc]


# Configure logging level based on environment
class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO")
    level = getattr(logging, log_level.upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    if settings.is_production or settings.is_staging:
        handler.setFormatter(_JsonLogFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)


_configure_logging()

logger = logging.getLogger(__name__)

SQLITE_ALLOWED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "tasks": (
        ("business_value", "FLOAT"),
        ("value_delivered", "BOOLEAN"),
        ("roi", "FLOAT"),
    ),
    "sprints": (
        ("velocity", "FLOAT"),
        ("commitment", "FLOAT"),
        ("completed", "FLOAT"),
        ("wip_limit", "INTEGER"),
    ),
    "pull_requests": (
        ("first_review_at", "TIMESTAMP"),
        ("cycle_time_hours", "FLOAT"),
        ("lead_time_hours", "FLOAT"),
        ("time_to_first_review_hours", "FLOAT"),
        ("rework_count", "INTEGER DEFAULT 0"),
        ("files_changed", "INTEGER"),
        ("lines_added", "INTEGER"),
        ("lines_deleted", "INTEGER"),
    ),
}

ALLOWED_CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
ALLOWED_CORS_HEADERS = [
    "Authorization",
    "Content-Type",
    "Accept",
]
ALEMBIC_VERSION_MIN_LENGTH = 64
ALEMBIC_VERSION_TARGET_LENGTH = 255


def _quote_sqlite_identifier(identifier: str) -> str:
    if not identifier or not identifier.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQLite identifier: {identifier!r}")
    return f'"{identifier}"'


def _get_engine_backend_name() -> str | None:
    engine_url = getattr(engine, "url", None)
    if engine_url is None:
        return None
    return engine_url.get_backend_name()


async def _ensure_postgres_alembic_runtime_state() -> None:
    """
    Verify that PostgreSQL runtime schema state is tracked by Alembic.

    Startup must fail fast when migration tracking is broken to avoid
    introducing further schema drift via runtime code paths.
    """
    if _get_engine_backend_name() != "postgresql":
        return

    async with engine.begin() as conn:
        schema_name = await conn.scalar(
            text(
                """
                SELECT n.nspname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'alembic_version'
                  AND c.relkind IN ('r', 'p')
                ORDER BY
                  CASE WHEN n.nspname = current_schema() THEN 0 ELSE 1 END,
                  n.nspname
                LIMIT 1
                """
            )
        )
        if not schema_name:
            raise RuntimeError(
                "Alembic runtime state is invalid: table alembic_version is missing. "
                "Run 'alembic upgrade head' before starting the API."
            )

        safe_schema = str(schema_name).replace('"', '""')
        alembic_table_qualified = f'"{safe_schema}"."alembic_version"'

        version_num_length = await conn.scalar(
            text(
                """
                SELECT character_maximum_length
                FROM information_schema.columns
                WHERE table_schema = :schema_name
                  AND table_name = 'alembic_version'
                  AND column_name = 'version_num'
                """
            ),
            {"schema_name": str(schema_name)},
        )
        if isinstance(version_num_length, int) and version_num_length < ALEMBIC_VERSION_MIN_LENGTH:
            await conn.execute(
                text(
                    f"ALTER TABLE {alembic_table_qualified} "
                    f"ALTER COLUMN version_num TYPE VARCHAR({ALEMBIC_VERSION_TARGET_LENGTH})"
                )
            )
            logger.warning(
                "Startup self-heal applied: widened alembic_version.version_num from %s to %s",
                version_num_length,
                ALEMBIC_VERSION_TARGET_LENGTH,
            )

        version_row_count = int(
            await conn.scalar(text(f"SELECT COUNT(*) FROM {alembic_table_qualified}")) or 0
        )
        if version_row_count != 1:
            raise RuntimeError(
                "Alembic runtime state is invalid: alembic_version must contain exactly one row "
                f"(found {version_row_count})."
            )

        current_revision = await conn.scalar(
            text(f"SELECT version_num FROM {alembic_table_qualified}")
        )
        if not current_revision:
            raise RuntimeError(
                "Alembic runtime state is invalid: alembic_version.version_num is empty."
            )

        logger.info(
            "Alembic runtime state verified (schema=%s revision=%s)", schema_name, current_revision
        )


def _is_https_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        proto = forwarded_proto.split(",")[0].strip().lower()
        return proto == "https"
    return request.url.scheme == "https"


def _is_loopback_host(host: str | None) -> bool:
    normalized = (host or "").strip().strip("[]").lower()
    if not normalized:
        return False
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _is_local_origin(origin: str) -> bool:
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    return _is_loopback_host(parsed.hostname)


def _validate_runtime_security_settings() -> None:
    if (settings.is_production or settings.is_staging) and settings.SECRET_KEY == (
        settings.SECRET_KEY_PLACEHOLDER
    ):
        raise RuntimeError(
            "SECRET_KEY is still the well-known placeholder; generate a unique "
            "secret before running in staging/production."
        )

    if (
        settings.is_production or settings.is_staging
    ) and not settings.has_strong_dedicated_encryption_secret:
        raise RuntimeError(
            "A strong dedicated ENCRYPTION_SECRET is required in staging/production for Jira/Confluence token storage."
        )

    if (settings.is_production or settings.is_staging) and settings.ALLOW_UNAUTHENTICATED_DEMO_API:
        raise RuntimeError(
            "ALLOW_UNAUTHENTICATED_DEMO_API cannot be enabled in staging/production."
        )

    if settings.ALLOW_UNAUTHENTICATED_DEMO_API:
        if not _is_loopback_host(settings.BACKEND_BIND_HOST):
            raise RuntimeError(
                "ALLOW_UNAUTHENTICATED_DEMO_API requires BACKEND_BIND_HOST to be a loopback address."
            )

        non_local_origins = [
            origin for origin in settings.CORS_ORIGINS if not _is_local_origin(origin)
        ]
        if non_local_origins:
            raise RuntimeError(
                "ALLOW_UNAUTHENTICATED_DEMO_API requires local-only CORS origins. "
                f"Non-local origins: {non_local_origins}"
            )


def _setup_sentry() -> None:
    if not hasattr(settings, "SENTRY_DSN") or not settings.SENTRY_DSN:
        logger.info("Sentry DSN not configured; skipping instrumentation")
        return
    integrations = [
        FastApiIntegration(),
        LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        SqlalchemyIntegration(),
    ]
    if CeleryIntegration is not None:
        integrations.append(CeleryIntegration())
    try:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            release=f"{settings.PROJECT_NAME}@{settings.VERSION}",
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            profiles_sample_rate=settings.SENTRY_PROFILES_SAMPLE_RATE,
            integrations=integrations,
        )
        logger.info(
            "Sentry initialised environment=%s release=%s", settings.ENVIRONMENT, settings.VERSION
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Sentry initialisation failed: %s", exc)


async def _ensure_sqlite_columns() -> None:
    try:
        if (
            (getattr(engine, "url", None) is None)
            or getattr(engine, "url", None) is None
            or engine.url.get_backend_name() != "sqlite"
        ):
            return
        async with engine.begin() as conn:

            async def ensure_columns(table: str):
                allowed_columns = SQLITE_ALLOWED_COLUMNS.get(table)
                if allowed_columns is None:
                    raise ValueError(f"SQLite startup migration attempted unknown table {table}")

                quoted_table = _quote_sqlite_identifier(table)
                res = await conn.execute(text(f"PRAGMA table_info({quoted_table})"))
                existing = {row[1] for row in res}
                to_add = [col for col in allowed_columns if col[0] not in existing]
                for column_name, column_type in to_add:
                    _quote_sqlite_identifier(column_name)
                    await conn.execute(
                        text(
                            f"ALTER TABLE {quoted_table} "
                            f"ADD COLUMN {_quote_sqlite_identifier(column_name)} {column_type}"
                        )
                    )

            for table_name in SQLITE_ALLOWED_COLUMNS:
                await ensure_columns(table_name)
    except Exception as e:
        logger.warning("SQLite column migration failed: %s", e)


async def _ensure_postgres_sync_tasks_schema() -> None:
    """Reconcile critical sync_tasks schema drift for PostgreSQL startup."""
    try:
        engine_url = getattr(engine, "url", None)
        if engine_url is None or engine_url.get_backend_name() != "postgresql":
            return

        async with engine.begin() as conn:
            alembic_table_exists = bool(
                await conn.scalar(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_class c
                            WHERE c.relname = 'alembic_version'
                              AND c.relkind IN ('r', 'p')
                        )
                        """
                    )
                )
            )
            if not alembic_table_exists:
                logger.warning(
                    "Schema drift diagnostic: alembic_version table is missing; "
                    "startup self-heal may indicate unapplied migrations"
                )

            sync_tasks_schema = await conn.scalar(
                text(
                    """
                    SELECT n.nspname
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = 'sync_tasks'
                      AND c.relkind IN ('r', 'p')
                    ORDER BY
                      CASE WHEN n.nspname = current_schema() THEN 0 ELSE 1 END,
                      n.nspname
                    LIMIT 1
                    """
                )
            )
            if not sync_tasks_schema:
                return

            safe_schema = str(sync_tasks_schema).replace('"', '""')
            sync_tasks_qualified = f'"{safe_schema}"."sync_tasks"'

            heartbeat_column_exists = bool(
                await conn.scalar(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_attribute a
                            JOIN pg_class c ON c.oid = a.attrelid
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relname = 'sync_tasks'
                              AND n.nspname = :schema_name
                              AND a.attname = 'heartbeat_at'
                              AND NOT a.attisdropped
                        )
                        """
                    ),
                    {"schema_name": str(sync_tasks_schema)},
                )
            )
            if not heartbeat_column_exists:
                await conn.execute(
                    text(
                        f"ALTER TABLE {sync_tasks_qualified} "
                        "ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ"
                    )
                )
                logger.warning("Startup self-heal applied: added sync_tasks.heartbeat_at")

            heartbeat_index_exists = bool(
                await conn.scalar(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM pg_class c
                            JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relkind = 'i'
                              AND c.relname = 'ix_sync_tasks_status_heartbeat'
                              AND n.nspname = :schema_name
                        )
                        """
                    ),
                    {"schema_name": str(sync_tasks_schema)},
                )
            )
            if not heartbeat_index_exists:
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_sync_tasks_status_heartbeat "
                        f"ON {sync_tasks_qualified} (status, heartbeat_at, started_at)"
                    )
                )
                logger.warning("Startup self-heal applied: created ix_sync_tasks_status_heartbeat")
    except Exception as exc:
        logger.warning("PostgreSQL sync_tasks schema reconciliation failed: %s", exc)


async def _ensure_system_roles() -> None:
    """Create/update system RBAC roles if they are missing."""
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                for role_name, role_config in SYSTEM_ROLES.items():
                    result = await db.execute(select(Role).where(Role.name == role_name))
                    role = result.scalar_one_or_none()

                    if role is None:
                        role = Role(
                            name=role_name,
                            display_name=role_config["display_name"],
                            description=role_config["description"],
                            is_system=role_config["is_system"],
                        )
                        role.permissions = role_config["permissions"]
                        db.add(role)
                    else:
                        role.display_name = role_config["display_name"]
                        role.description = role_config["description"]
                        role.is_system = role_config["is_system"]
                        role.permissions = role_config["permissions"]
        logger.info("RBAC system roles ensured successfully")
    except Exception as exc:
        logger.error("RBAC role initialization failed during startup: %s", exc)


async def _ensure_tables():
    # Keep auto-bootstrap only for SQLite. PostgreSQL must be migration-managed.
    try:
        backend_name = _get_engine_backend_name()
        if backend_name == "sqlite":
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        elif backend_name == "postgresql":
            await _ensure_postgres_alembic_runtime_state()

        await _ensure_postgres_sync_tasks_schema()
        await _ensure_sqlite_columns()
        await _ensure_system_roles()
        logger.info("Database schema ensured successfully")
    except Exception as exc:
        logger.error("Database initialization failed during startup: %s", exc)
        raise

    # Skip auto-connect if SKIP_SERVICE_AUTOCONNECT is set
    if settings.SKIP_SERVICE_AUTOCONNECT:
        logger.info("Skipping service auto-connect due to SKIP_SERVICE_AUTOCONNECT=true")
        return

    # Try to auto-connect services from stored settings with timeout
    import asyncio

    try:
        # Add timeout to prevent hanging on startup
        async def auto_connect_with_timeout():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(IntegrationSetting))
                rows = res.scalars().all()
                for row in rows:
                    if row.kind == "jira" and (row.base_url and row.api_token):
                        token = await load_integration_token(db, row)
                        if not token:
                            logger.warning(
                                "Skipping Jira auto-connect: stored token could not be decrypted (base_url=%s)",
                                row.base_url,
                            )
                            continue
                        try:
                            use_pat = bool(
                                getattr(settings, "JIRA_FORCE_PAT", False) or not row.email
                            )
                            email_to_use = None if use_pat else row.email
                            connect_fn = partial(
                                jira_service.connect, row.base_url, email_to_use, token, use_pat
                            )
                            # Create connection task with timeout
                            await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(None, connect_fn),
                                timeout=5.0,  # 5 second timeout per connection
                            )
                            logger.info(
                                "Jira auto-connected from stored settings (base_url=%s mode=%s)",
                                row.base_url,
                                "PAT" if use_pat else "Basic",
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Auto-connect to Jira timed out (base_url=%s)", row.base_url
                            )
                        except Exception as exc:
                            logger.warning(
                                "Auto-connect to Jira failed (base_url=%s): %s", row.base_url, exc
                            )
                    if row.kind == "confluence" and (row.base_url and row.api_token):
                        token = await load_integration_token(db, row)
                        if not token:
                            logger.warning(
                                "Skipping Confluence auto-connect: stored token could not be decrypted (base_url=%s)",
                                row.base_url,
                            )
                            continue
                        try:
                            # Create connection task with timeout
                            await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, confluence_service.connect, row.base_url, row.email, token
                                ),
                                timeout=5.0,  # 5 second timeout per connection
                            )
                            logger.info(
                                "Confluence auto-connected from stored settings (base_url=%s)",
                                row.base_url,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                "Auto-connect to Confluence timed out (base_url=%s)", row.base_url
                            )
                        except Exception as exc:
                            logger.warning(
                                "Auto-connect to Confluence failed (base_url=%s): %s",
                                row.base_url,
                                exc,
                            )

        # Apply overall timeout for all auto-connections
        await asyncio.wait_for(auto_connect_with_timeout(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.error("Service auto-connect timed out after 15 seconds")
    except Exception as exc:
        logger.error("Service auto-connect bootstrap failed: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _ensure_tables()
    yield


_setup_sentry()
_validate_runtime_security_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

logger.info(
    "Starting %s v%s (env=%s)", settings.PROJECT_NAME, settings.VERSION, settings.ENVIRONMENT
)
if settings.is_production and settings.DEBUG:
    logger.warning("DEBUG is enabled while ENVIRONMENT=production; forcing DEBUG=False")
    settings.DEBUG = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=ALLOWED_CORS_METHODS,
    allow_headers=ALLOWED_CORS_HEADERS,
)

register_middlewares(app)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    )
    if (settings.is_production or settings.is_staging) and _is_https_request(request):
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_STR}/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
