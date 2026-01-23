import os

# Ensure configuration exists before the app loads settings.
TEST_SECRET = "test-secret-key-should-be-long-enough-1234567890"
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
os.environ.setdefault("SECRET_KEY", TEST_SECRET)
os.environ.setdefault("ENCRYPTION_SECRET", TEST_SECRET)
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("SKIP_SERVICE_AUTOCONNECT", "1")
os.environ.setdefault("JIRA_BASE_URL", "")
os.environ.setdefault("JIRA_EMAIL", "")
os.environ.setdefault("JIRA_API_TOKEN", "")
os.environ.setdefault("ENABLE_MATRIX_CACHE", "false")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("GOOGLE_CLIENT_ID", "")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "")
os.environ.setdefault("MICROSOFT_CLIENT_ID", "")
os.environ.setdefault("MICROSOFT_CLIENT_SECRET", "")

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.main import app
from app.core.database import AsyncSessionLocal, Base, engine, get_db
from app.api.deps import get_current_user
from app.core import cache_enhanced
from app.core.rate_limit import limiter


class _DummyUser:
    id = 1
    email = "test@example.com"
    username = "test"
    full_name = "Test User"
    is_active = True
    is_superuser = True
    mfa_enabled = False
    mfa_secret = None
    mfa_backup_codes = None

    def has_permission(self, _permission: str) -> bool:
        return True

    def has_role(self, _role: str) -> bool:
        return True

    @property
    def mfa_configured(self) -> bool:
        return bool(self.mfa_secret)

    @property
    def remaining_backup_codes(self) -> int:
        return len(self.mfa_backup_codes or [])


async def _override_get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def _override_get_current_user():
    return _DummyUser()


app.dependency_overrides[get_db] = _override_get_db
app.dependency_overrides[get_current_user] = _override_get_current_user
limiter.enabled = False
limiter._headers_enabled = False


@pytest_asyncio.fixture
async def db_session():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    async with AsyncClient(app=app, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def reset_cache():
    cache_enhanced.enhanced_cache_service = cache_enhanced.EnhancedCacheService(None)
    return None
