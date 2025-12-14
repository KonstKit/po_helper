from typing import AsyncIterator
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def create_optimized_engine() -> AsyncEngine:
    """Create database engine with optimized settings for SQLite."""
    _url = make_url(str(settings.DATABASE_URL))
    engine_kwargs: dict[str, object] = {
        'echo': False,
    }

    if _url.get_backend_name() != 'sqlite':
        # PostgreSQL/MySQL settings
        engine_kwargs.update({
            'pool_size': settings.DB_POOL_SIZE,
            'max_overflow': settings.DB_POOL_MAX_OVERFLOW,
            'pool_timeout': settings.DB_POOL_TIMEOUT,
            'pool_recycle': settings.DB_POOL_RECYCLE,
            'pool_pre_ping': settings.DB_POOL_PRE_PING,
        })
    else:
        # SQLite optimizations
        engine_kwargs.update({
            'pool_pre_ping': True,
            'connect_args': {
                'check_same_thread': False,
                'timeout': 30.0,  # Connection timeout in seconds
            }
        })

    engine = create_async_engine(
        str(settings.DATABASE_URL),
        **engine_kwargs,
    )

    # Configure SQLite pragmas for better performance
    if _url.get_backend_name() == 'sqlite':
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            # Enable WAL mode for concurrent reads
            cursor.execute("PRAGMA journal_mode=WAL")
            # Set busy timeout to 30 seconds (30000 ms)
            cursor.execute("PRAGMA busy_timeout=30000")
            # Optimize for performance
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA mmap_size=30000000000")
            # Increase cache size (negative = KB, default is -2000 = 2MB)
            cursor.execute("PRAGMA cache_size=-64000")  # 64MB cache
            cursor.close()
            logger.info("SQLite optimizations applied: WAL mode enabled")

    return engine


# Create optimized engine
engine = create_optimized_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()