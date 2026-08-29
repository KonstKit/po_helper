from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.api_v1.endpoints import auth as auth_module
from app.api.api_v1.endpoints.git import webhooks as git_webhooks
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.rate_limit import limiter
from app.core.middleware import register_middlewares
import app.main as app_main
from app.main import _JsonLogFormatter, ALLOWED_CORS_HEADERS, ALLOWED_CORS_METHODS, app
from app.models import Role


@pytest.mark.asyncio
async def test_security_headers_are_emitted_and_hsts_is_https_only(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    async with AsyncClient(app=app, base_url="http://test") as client:
        http_response = await client.get("/health")
    async with AsyncClient(app=app, base_url="https://test") as client:
        https_response = await client.get("/health")

    for response in (http_response, https_response):
        assert response.status_code == 200
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert (
            response.headers["Content-Security-Policy"]
            == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )

    assert "Strict-Transport-Security" not in http_response.headers
    assert (
        https_response.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"
    )


def test_cors_configuration_uses_explicit_allowlists():
    cors_middleware = next(
        middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware
    )

    assert cors_middleware.kwargs["allow_methods"] == ALLOWED_CORS_METHODS
    assert cors_middleware.kwargs["allow_headers"] == ALLOWED_CORS_HEADERS
    assert "*" not in cors_middleware.kwargs["allow_methods"]
    assert "*" not in cors_middleware.kwargs["allow_headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "secret_attr", "payload", "headers"),
    [
        (
            "/api/v1/git/webhooks/github",
            "GITHUB_WEBHOOK_SECRET",
            {"ref": "refs/heads/main", "repository": {"full_name": "owner/repo"}},
            {"X-GitHub-Event": "push", "Content-Type": "application/json"},
        ),
        (
            "/api/v1/git/webhooks/gitlab",
            "GITLAB_WEBHOOK_SECRET",
            {
                "object_kind": "push",
                "project": {"path_with_namespace": "group/repo"},
                "commits": [],
            },
            {"Content-Type": "application/json"},
        ),
    ],
)
async def test_webhooks_reject_missing_secret_in_production(
    monkeypatch,
    path: str,
    secret_attr: str,
    payload: dict[str, object],
    headers: dict[str, str],
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, secret_attr, None)
    monkeypatch.setattr(git_webhooks.webhook_breaker, "allow", lambda _provider: True)
    monkeypatch.setattr(git_webhooks.webhook_limiter, "check_rate", lambda _provider: True)

    class _Request:
        def __init__(self) -> None:
            self.headers = headers

        async def body(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

        async def json(self) -> dict[str, object]:
            return payload

    request = _Request()

    with pytest.raises(HTTPException) as exc_info:
        if path.endswith("/github"):
            await git_webhooks.handle_github_webhook(request, SimpleNamespace())
        else:
            await git_webhooks.handle_gitlab_webhook(request, SimpleNamespace())

    assert exc_info.value.status_code == 503
    assert "webhook secret is not configured" in exc_info.value.detail


@pytest.mark.asyncio
async def test_register_rate_limit_returns_429_after_three_requests(monkeypatch):
    limiter.reset()
    monkeypatch.setattr(limiter, "enabled", True)

    db_file = Path("register_contract_test.db")
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db_file}{suffix}").unlink(missing_ok=True)

    engine = create_async_engine(f"sqlite+aiosqlite:///./{db_file}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    temp_app = FastAPI()
    register_middlewares(temp_app)
    temp_app.include_router(auth_module.router, prefix="/api/v1/auth")

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    temp_app.dependency_overrides[get_db] = _override_get_db

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncClient(app=temp_app, base_url="http://test") as client:
            statuses: list[int] = []
            for index in range(4):
                response = await client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"limit-{index}@example.com",
                        "username": f"limit-user-{index}",
                        "full_name": f"Limit User {index}",
                        "password": "StrongPassword123!",
                    },
                )
                statuses.append(response.status_code)

        assert statuses[:3] == [200, 200, 200]
        assert statuses[3] == 429
    finally:
        limiter.reset()
        await engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_file}{suffix}").unlink(missing_ok=True)


def test_production_logging_uses_json_formatter(monkeypatch):
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    try:
        app_main._configure_logging()

        assert any(
            isinstance(handler.formatter, _JsonLogFormatter) for handler in root_logger.handlers
        )

        formatter = next(
            handler.formatter
            for handler in root_logger.handlers
            if isinstance(handler.formatter, _JsonLogFormatter)
        )
        record = logging.LogRecord(
            name="po_helper.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="structured logging smoke",
            args=(),
            exc_info=None,
        )
        payload = json.loads(formatter.format(record))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "po_helper.test"
        assert payload["message"] == "structured logging smoke"
        assert "timestamp" in payload
    finally:
        root_logger.handlers[:] = original_handlers
        root_logger.setLevel(original_level)


def test_runtime_security_requires_dedicated_encryption_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", None)

    with pytest.raises(RuntimeError, match="strong dedicated ENCRYPTION_SECRET is required"):
        app_main._validate_runtime_security_settings()


def test_runtime_security_rejects_shared_encryption_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", "shared-secret")

    with pytest.raises(RuntimeError, match="strong dedicated ENCRYPTION_SECRET is required"):
        app_main._validate_runtime_security_settings()


def test_runtime_security_rejects_placeholder_encryption_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", "generate-another-secret-key-here")

    with pytest.raises(RuntimeError, match="strong dedicated ENCRYPTION_SECRET is required"):
        app_main._validate_runtime_security_settings()


def test_runtime_security_accepts_strong_encryption_secret_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", "B4ckendEnc!Secret_2026_LocalDemo#001234")
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    app_main._validate_runtime_security_settings()


def test_runtime_security_rejects_demo_bypass_on_non_loopback_bind(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)
    monkeypatch.setattr(settings, "BACKEND_BIND_HOST", "0.0.0.0")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["http://127.0.0.1:3000"])

    with pytest.raises(RuntimeError, match="BACKEND_BIND_HOST"):
        app_main._validate_runtime_security_settings()


def test_runtime_security_rejects_demo_bypass_with_non_local_cors(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)
    monkeypatch.setattr(settings, "BACKEND_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://demo.example.com"])

    with pytest.raises(RuntimeError, match="local-only CORS origins"):
        app_main._validate_runtime_security_settings()


def test_runtime_security_allows_local_demo_bypass_with_loopback_bind(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)
    monkeypatch.setattr(settings, "BACKEND_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(
        settings,
        "CORS_ORIGINS",
        ["http://localhost:3000", "http://127.0.0.1:5173"],
    )

    app_main._validate_runtime_security_settings()
