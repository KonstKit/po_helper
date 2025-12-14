from typing import AsyncIterator
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import event
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


_url = make_url(str(settings.DATABASE_URL))
engine_kwargs: dict[str, object] = {
    'echo': False,
}

if _url.get_backend_name() != 'sqlite':
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
            'timeout': 30.0,  # Connection timeout
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
        # Set busy timeout to 30 seconds
        cursor.execute("PRAGMA busy_timeout=30000")
        # Optimize for performance
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA mmap_size=30000000000")
        # Increase cache size
        cursor.execute("PRAGMA cache_size=-64000")  # 64MB
        cursor.close()
        logger.info("SQLite optimizations applied: WAL mode enabled")

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,  # Explicitly set autocommit to False
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
