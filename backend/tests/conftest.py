import importlib
import os

import pytest
import pytest_asyncio
from httpx import AsyncClient

from tests._flaky_quarantine import (
    build_flaky_quarantine_skip_reason,
    validate_flaky_quarantine_metadata,
)
from tests._sqlite_schema import reset_sqlite_schema

# Ensure configuration exists before the app loads settings.
TEST_SECRET = "test-secret-key-should-be-long-enough-1234567890"
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = TEST_SECRET
os.environ["ENCRYPTION_SECRET"] = TEST_SECRET
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SKIP_SERVICE_AUTOCONNECT"] = "1"
os.environ["JIRA_BASE_URL"] = ""
os.environ["JIRA_EMAIL"] = ""
os.environ["JIRA_API_TOKEN"] = ""
os.environ["ENABLE_MATRIX_CACHE"] = "false"
os.environ["REDIS_URL"] = ""
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["GOOGLE_CLIENT_SECRET"] = ""
os.environ["MICROSOFT_CLIENT_ID"] = ""
os.environ["MICROSOFT_CLIENT_SECRET"] = ""

import app.models  # noqa: F401  # Register all ORM models before the app/engine loads.

app = importlib.import_module("app.main").app
db_module = importlib.import_module("app.core.database")
AsyncSessionLocal = db_module.AsyncSessionLocal
get_db = db_module.get_db
get_current_user = importlib.import_module("app.api.deps").get_current_user
require_integration_access = importlib.import_module("app.api.deps").require_integration_access
cache_enhanced = importlib.import_module("app.core.cache_enhanced")
limiter = importlib.import_module("app.core.rate_limit").limiter


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
app.dependency_overrides[require_integration_access] = _override_get_current_user
limiter.enabled = False
limiter._headers_enabled = False


def pytest_addoption(parser):
    parser.addoption(
        "--run-flaky-quarantine",
        action="store_true",
        default=False,
        help="Execute tests marked with flaky_quarantine.",
    )


def pytest_collection_modifyitems(config, items):
    run_quarantined = bool(config.getoption("--run-flaky-quarantine"))
    policy_errors: list[str] = []

    for item in items:
        marker = item.get_closest_marker("flaky_quarantine")
        if marker is None:
            continue

        try:
            metadata = validate_flaky_quarantine_metadata(marker.kwargs)
        except ValueError as exc:
            policy_errors.append(f"{item.nodeid}: {exc}")
            continue

        if not run_quarantined:
            item.add_marker(
                pytest.mark.skip(reason=build_flaky_quarantine_skip_reason(metadata))
            )

    if policy_errors:
        details = "\n- ".join(policy_errors)
        raise pytest.UsageError(
            "Invalid flaky_quarantine marker configuration:\n- " + details
        )


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def reset_db_schema():
    """Ensure a clean SQLite schema before each test."""
    await reset_sqlite_schema()
    yield


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def reset_cache():
    cache_enhanced.enhanced_cache_service = cache_enhanced.EnhancedCacheService(None)
    return None
