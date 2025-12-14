import logging
import os
from functools import partial

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
try:
    from sentry_sdk.integrations.celery import CeleryIntegration
except ImportError:  # pragma: no cover - Celery optional
    CeleryIntegration = None  # type: ignore

# Configure logging level based on environment
log_level = os.getenv('LOG_LEVEL', 'INFO')
logging.basicConfig(
    level=getattr(logging, log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1.api import api_router
from app.core.database import engine, Base, AsyncSessionLocal
from sqlalchemy import select, text
from app.models.settings import IntegrationSetting
from app.services.jira_service import jira_service
from app.services.confluence_service import confluence_service
from app.core.crypto import decrypt_str
from app.core.middleware import register_middlewares
from app.api.ws import router as ws_router

logger = logging.getLogger(__name__)


def _setup_sentry() -> None:
    if not hasattr(settings, 'SENTRY_DSN') or not settings.SENTRY_DSN:
        logger.info('Sentry DSN not configured; skipping instrumentation')
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
        logger.info('Sentry initialised environment=%s release=%s', settings.ENVIRONMENT, settings.VERSION)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error('Sentry initialisation failed: %s', exc)


_setup_sentry()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

logger.info('Starting %s v%s (env=%s)', settings.PROJECT_NAME, settings.VERSION, settings.ENVIRONMENT)
if settings.is_production and settings.DEBUG:
    logger.warning('DEBUG is enabled while ENVIRONMENT=production; forcing DEBUG=False')
    settings.DEBUG = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_middlewares(app)

app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(ws_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": f"{settings.API_V1_STR}/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


async def _ensure_sqlite_columns() -> None:
    try:
        if (getattr(engine, 'url', None) is None) or getattr(engine, 'url', None) is None or engine.url.get_backend_name() != 'sqlite':
            return
        async with engine.begin() as conn:
            async def ensure_columns(table: str, columns: list[tuple[str, str]]):
                res = await conn.execute(text(f"PRAGMA table_info({table})"))
                existing = {row[1] for row in res}
                to_add = [col for col in columns if col[0] not in existing]
                for column_name, column_type in to_add:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"))

            await ensure_columns('tasks', [
                ('business_value', 'FLOAT'),
                ('value_delivered', 'BOOLEAN'),
                ('roi', 'FLOAT'),
            ])

            await ensure_columns('sprints', [
                ('velocity', 'FLOAT'),
                ('commitment', 'FLOAT'),
                ('completed', 'FLOAT'),
                ('wip_limit', 'INTEGER'),
            ])

            await ensure_columns('pull_requests', [
                ('first_review_at', 'TIMESTAMP'),
                ('cycle_time_hours', 'FLOAT'),
                ('lead_time_hours', 'FLOAT'),
                ('time_to_first_review_hours', 'FLOAT'),
                ('rework_count', 'INTEGER DEFAULT 0'),
                ('files_changed', 'INTEGER'),
                ('lines_added', 'INTEGER'),
                ('lines_deleted', 'INTEGER'),
            ])
    except Exception as e:
        logger.warning("SQLite column migration failed: %s", e)


@app.on_event("startup")
async def _ensure_tables():
    # Dev-friendly: auto-create tables if missing (SQLite / simple schemas)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await _ensure_sqlite_columns()
        logger.info("Database schema ensured successfully")
    except Exception as exc:
        logger.error("Database initialization failed during startup: %s", exc)

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
                    if row.kind == 'jira' and (row.base_url and row.api_token):
                        token = decrypt_str(row.api_token)
                        try:
                            use_pat = bool(getattr(settings, 'JIRA_FORCE_PAT', False) or not row.email)
                            email_to_use = None if use_pat else row.email
                            connect_fn = partial(jira_service.connect, row.base_url, email_to_use, token, use_pat)
                            # Create connection task with timeout
                            await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, connect_fn
                                ),
                                timeout=5.0  # 5 second timeout per connection
                            )
                            logger.info("Jira auto-connected from stored settings (base_url=%s mode=%s)", row.base_url, 'PAT' if use_pat else 'Basic')
                        except asyncio.TimeoutError:
                            logger.warning("Auto-connect to Jira timed out (base_url=%s)", row.base_url)
                        except Exception as exc:
                            logger.warning("Auto-connect to Jira failed (base_url=%s): %s", row.base_url, exc)
                    if row.kind == 'confluence' and (row.base_url and row.api_token):
                        token = decrypt_str(row.api_token)
                        try:
                            # Create connection task with timeout
                            await asyncio.wait_for(
                                asyncio.get_event_loop().run_in_executor(
                                    None, confluence_service.connect, row.base_url, row.email, token
                                ),
                                timeout=5.0  # 5 second timeout per connection
                            )
                            logger.info("Confluence auto-connected from stored settings (base_url=%s)", row.base_url)
                        except asyncio.TimeoutError:
                            logger.warning("Auto-connect to Confluence timed out (base_url=%s)", row.base_url)
                        except Exception as exc:
                            logger.warning("Auto-connect to Confluence failed (base_url=%s): %s", row.base_url, exc)

        # Apply overall timeout for all auto-connections
        await asyncio.wait_for(auto_connect_with_timeout(), timeout=15.0)
    except asyncio.TimeoutError:
        logger.error("Service auto-connect timed out after 15 seconds")
    except Exception as exc:
        logger.error("Service auto-connect bootstrap failed: %s", exc)

