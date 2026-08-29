from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_integration_access
from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.models import User


@pytest.fixture
def use_real_integration_access():
    original = app.dependency_overrides.pop(require_integration_access, None)
    yield
    if original is not None:
        app.dependency_overrides[require_integration_access] = original
    else:
        app.dependency_overrides.pop(require_integration_access, None)


async def _create_auth_headers(
    db_session, suffix: str, *, privileged: bool = False
) -> dict[str, str]:
    user = User(
        email=f"integration-{suffix}@example.com",
        username=f"integration-{suffix}",
        full_name="Integration Test User",
        hashed_password=None,
        is_active=True,
        # connect endpoints require integration:manage since the security
        # review; superuser passes the gate for contract-focused tests.
        is_superuser=privileged,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token({"sub": user.email})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_jira_connect_requires_login_by_default(
    client,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    response = await client.post(
        "/api/v1/jira/connect",
        json={
            "base_url": "https://example.atlassian.net",
            "api_token": "token",
            "email": "user@example.com",
            "use_pat": False,
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_jira_connect_accepts_authenticated_json_body_and_rejects_query_contract(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    async def _fake_call_jira(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr("app.api.api_v1.endpoints.jira._call_jira", _fake_call_jira)
    headers = await _create_auth_headers(db_session, "jira-auth", privileged=True)

    response = await client.post(
        "/api/v1/jira/connect",
        json={
            "base_url": "https://example.atlassian.net",
            "api_token": "token",
            "email": "user@example.com",
            "use_pat": False,
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"

    legacy_response = await client.post(
        "/api/v1/jira/connect?base_url=https://example.atlassian.net&api_token=token",
        headers=headers,
    )

    assert legacy_response.status_code == 422


@pytest.mark.asyncio
async def test_jira_connect_allows_unauthenticated_demo_bypass(
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)

    async def _fake_call_jira(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr("app.api.api_v1.endpoints.jira._call_jira", _fake_call_jira)

    async with AsyncClient(app=app, base_url="http://127.0.0.1") as local_client:
        response = await local_client.post(
            "/api/v1/jira/connect",
            json={
                "base_url": "https://example.atlassian.net",
                "api_token": "token",
                "email": "user@example.com",
                "use_pat": False,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"


@pytest.mark.asyncio
async def test_confluence_connect_requires_login_by_default(
    client,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    response = await client.post(
        "/api/v1/confluence/connect",
        json={
            "base_url": "https://example.atlassian.net/wiki",
            "api_token": "token",
            "email": "user@example.com",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_confluence_connect_accepts_authenticated_json_body_and_rejects_query_contract(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    async def _fake_call_confluence(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.confluence._call_confluence", _fake_call_confluence
    )
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.confluence.confluence_service.status",
        lambda: {"configured": True},
    )
    headers = await _create_auth_headers(db_session, "confluence-auth", privileged=True)

    response = await client.post(
        "/api/v1/confluence/connect",
        json={
            "base_url": "https://example.atlassian.net/wiki",
            "api_token": "token",
            "email": "user@example.com",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"
    assert response.json()["configured"] is True

    legacy_response = await client.post(
        "/api/v1/confluence/connect?base_url=https://example.atlassian.net/wiki&api_token=token",
        headers=headers,
    )

    assert legacy_response.status_code == 422


@pytest.mark.asyncio
async def test_confluence_connect_allows_unauthenticated_demo_bypass(
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)

    async def _fake_call_confluence(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr(
        "app.api.api_v1.endpoints.confluence._call_confluence", _fake_call_confluence
    )
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.confluence.confluence_service.status",
        lambda: {"configured": True},
    )

    async with AsyncClient(app=app, base_url="http://127.0.0.1") as local_client:
        response = await local_client.post(
            "/api/v1/confluence/connect",
            json={
                "base_url": "https://example.atlassian.net/wiki",
                "api_token": "token",
                "email": "user@example.com",
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "connected"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/jira/projects/WAB/sync"),
        ("post", "/api/v1/confluence/sync"),
        ("get", "/api/v1/confluence/sync-sse"),
        ("post", "/api/v1/confluence/sync-celery"),
        ("get", "/api/v1/confluence/sync-celery-stream/test-channel"),
    ],
)
async def test_sync_endpoints_require_login_by_default(
    client,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
    method: str,
    path: str,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    response = await getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/jira/status"),
        ("get", "/api/v1/jira/projects"),
        ("get", "/api/v1/jira/projects/WAB/check"),
        ("get", "/api/v1/jira/projects/WAB/boards"),
        ("get", "/api/v1/jira/projects/WAB"),
        ("get", "/api/v1/jira/projects/WAB/issues"),
        ("get", "/api/v1/jira/sprints/1/active"),
        ("get", "/api/v1/jira/issues/WAB-1/worklogs"),
        ("get", "/api/v1/jira/debug/WAB"),
    ],
)
async def test_jira_read_endpoints_require_login_by_default(
    client,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
    method: str,
    path: str,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    response = await getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/confluence/status"),
        ("get", "/api/v1/confluence/search?cql=type=page"),
        ("get", "/api/v1/confluence/spaces"),
        ("get", "/api/v1/confluence/pages"),
        ("get", "/api/v1/confluence/local/pages"),
        ("get", "/api/v1/confluence/spaces/ENG/tree"),
        ("get", "/api/v1/confluence/pages/123"),
        ("get", "/api/v1/confluence/prd/123/requirements"),
        ("get", "/api/v1/confluence/adr/123"),
        ("get", "/api/v1/confluence/research/123"),
    ],
)
async def test_confluence_read_endpoints_require_login_by_default(
    client,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
    method: str,
    path: str,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)

    response = await getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_jira_status_accepts_authenticated_request(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.jira.jira_service.status",
        lambda: {"configured": True, "auth_mode": "PAT"},
    )
    headers = await _create_auth_headers(db_session, "jira-status")

    response = await client.get("/api/v1/jira/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"configured": True, "auth_mode": "PAT"}


@pytest.mark.asyncio
async def test_confluence_status_accepts_authenticated_request(
    client,
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", False)
    monkeypatch.setattr(
        "app.api.api_v1.endpoints.confluence.confluence_service.status",
        lambda: {"configured": True, "instance_type": "cloud"},
    )
    headers = await _create_auth_headers(db_session, "confluence-status")

    response = await client.get("/api/v1/confluence/status", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"configured": True, "instance_type": "cloud"}


@pytest.mark.asyncio
async def test_demo_bypass_rejects_non_local_origin(
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)

    async def _fake_call_jira(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr("app.api.api_v1.endpoints.jira._call_jira", _fake_call_jira)

    async with AsyncClient(app=app, base_url="http://127.0.0.1") as local_client:
        response = await local_client.post(
            "/api/v1/jira/connect",
            headers={"Origin": "https://example.com"},
            json={
                "base_url": "https://example.atlassian.net",
                "api_token": "token",
                "email": "user@example.com",
                "use_pat": False,
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"


@pytest.mark.asyncio
async def test_demo_bypass_rejects_non_local_client(
    monkeypatch: pytest.MonkeyPatch,
    use_real_integration_access,
):
    monkeypatch.setattr(settings, "ALLOW_UNAUTHENTICATED_DEMO_API", True)

    async def _fake_call_jira(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        del func, args, kwargs
        return None

    monkeypatch.setattr("app.api.api_v1.endpoints.jira._call_jira", _fake_call_jira)

    transport = ASGITransport(app=app, client=("203.0.113.10", 4242))
    async with AsyncClient(
        transport=transport,
        base_url="http://127.0.0.1",
    ) as remote_client:
        response = await remote_client.post(
            "/api/v1/jira/connect",
            json={
                "base_url": "https://example.atlassian.net",
                "api_token": "token",
                "email": "user@example.com",
                "use_pat": False,
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
