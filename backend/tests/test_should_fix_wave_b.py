"""Wave B regression tests from the Should Fix roadmap (docs/SHOULD_FIX_ROADMAP.md).

B1: MFA secret stored AES-GCM-encrypted, backup codes stored as SHA-256;
    legacy plaintext storage is upgraded on first touch.
B2: replayed TOTP codes are rejected via mfa_last_used_counter.
B3: rate limiter resolves shared Redis storage when reachable and falls
    back loudly; auth limit is wired from settings.
B4: DEBUG alone no longer grants the demo admin; explicit
    ALLOW_DEBUG_DEMO_USER is required.
B5: encrypt_str refuses to store plaintext without any configured secret.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pyotp
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import _resolve_current_user
from app.core.config import settings
from app.core.crypto import AES_GCM_PREFIX, decrypt_str, encrypt_str
from app.core.database import AsyncSessionLocal
from app.core.mfa import hash_backup_codes, verify_backup_code
from app.core.rate_limit import _resolve_storage_uri
from app.main import app
from app.models import User
from tests.test_blocker_fixes import _real_integration_access, _register_and_login


@pytest.fixture(autouse=True)
def _dedicated_encryption_secret(monkeypatch):
    """conftest reuses SECRET_KEY for ENCRYPTION_SECRET; encryption helpers
    require a dedicated value distinct from the signing key."""
    monkeypatch.setattr(
        settings,
        "ENCRYPTION_SECRET",
        "dedicated-test-encryption-secret-0123456789abcdef",
    )


async def _get_user_by_email(email: str) -> User:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        await db.refresh(user, attribute_names=["roles"])
        return user


# ---------------------------------------------------------------------------
# B4: debug demo user behind an explicit flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_debug_alone_does_not_grant_demo_admin(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ALLOW_DEBUG_DEMO_USER", False)

    with pytest.raises(HTTPException) as exc_info:
        await _resolve_current_user(db_session, authorization=None, allow_debug_demo_fallback=True)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_debug_demo_user_requires_explicit_flag(db_session, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    monkeypatch.setattr(settings, "ALLOW_DEBUG_DEMO_USER", True)

    user = await _resolve_current_user(
        db_session, authorization=None, allow_debug_demo_fallback=True
    )
    assert user.email == "demo@example.com"


# ---------------------------------------------------------------------------
# B5: encrypt_str refuses plaintext fallback
# ---------------------------------------------------------------------------


def test_encrypt_str_raises_without_any_secret(monkeypatch):
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "")
    with pytest.raises(RuntimeError, match="refusing to store plaintext"):
        encrypt_str("super-secret-token")


def test_encrypt_str_roundtrip_with_secret():
    token = "ghp_example_token_value"
    encrypted = encrypt_str(token)
    assert encrypted.startswith(AES_GCM_PREFIX)
    assert decrypt_str(encrypted) == token


@pytest.mark.asyncio
async def test_settings_token_save_fails_loudly_without_secrets(client, monkeypatch):
    """Codex r1 MF4: when encryption refuses to store plaintext, the
    settings endpoints must return an explicit 503 - not a silent 200."""
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", None)
    monkeypatch.setattr(settings, "SECRET_KEY", "")

    response = await client.put(
        "/api/v1/settings/github",
        json={"base_url": "https://api.github.com", "api_token": "ghp_x"},
    )
    assert response.status_code == 503
    assert "ENCRYPTION_SECRET" in response.json()["detail"]


# ---------------------------------------------------------------------------
# B1 + B2: MFA storage hardening and TOTP anti-replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mfa_setup_stores_encrypted_secret_and_hashed_codes(client):
    token = await _register_and_login(client, "mfa-b1@example.com", "mfa_b1_user")

    with _real_integration_access():
        response = await client.post(
            "/api/v1/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    secret = response.json()["secret"]
    plain_codes = response.json()["backup_codes"]

    user = await _get_user_by_email("mfa-b1@example.com")
    # at rest: encrypted secret, bcrypt-hashed backup codes
    assert user.mfa_secret.startswith(AES_GCM_PREFIX)
    assert user.mfa_secret != secret
    assert all(code.startswith("$2") for code in user.mfa_backup_codes or [])
    assert secret not in (user.mfa_backup_codes or [])
    # verification still works against the digests
    valid, idx = verify_backup_code(plain_codes[0], user.mfa_backup_codes or [])
    assert valid and idx == 0


@pytest.mark.asyncio
async def test_mfa_login_flow_and_totp_replay_rejected(client):
    token = await _register_and_login(client, "mfa-b2@example.com", "mfa_b2_user")

    with _real_integration_access():
        setup = await client.post(
            "/api/v1/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"}
        )
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()

    with _real_integration_access():
        verify = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert verify.status_code == 200, verify.text

    # login requires MFA now
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "mfa-b2@example.com", "password": "StrongPassword123!"},
    )
    assert login.json().get("mfa_required") is True
    temp_token = login.json()["temp_token"]

    # the setup step above already consumed the current window's code
    # (anti-replay), so use exactly the NEXT interval: now+32s can be two
    # windows ahead when the current window has <2s left (+1 is the max
    # the verifier accepts)
    import time as _time
    from datetime import datetime

    next_interval = (int(_time.time()) // 30 + 1) * 30
    fresh_code = pyotp.TOTP(secret).at(datetime.fromtimestamp(next_interval))
    first = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": fresh_code, "temp_token": temp_token},
    )
    assert first.status_code == 200, first.text

    # B2: replaying the same code must fail even inside its validity window
    login2 = await client.post(
        "/api/v1/auth/login",
        data={"username": "mfa-b2@example.com", "password": "StrongPassword123!"},
    )
    replay = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": fresh_code, "temp_token": login2.json()["temp_token"]},
    )
    assert replay.status_code in (400, 401)


@pytest.mark.asyncio
async def test_legacy_plaintext_mfa_storage_upgraded_on_use(client, monkeypatch):
    """Pre-wave-B rows (plaintext secret + plaintext codes) keep working and
    are migrated to encrypted/hashed storage on the first MFA operation."""
    from app.core.security import get_password_hash

    email = "mfa-legacy@example.com"
    plaintext_secret = pyotp.random_base32()
    legacy_codes = ["ABCD-1234", "EFGH-5678"]

    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                username="mfa_legacy_user",
                hashed_password=get_password_hash("StrongPassword123!"),
                is_active=True,
                mfa_enabled=True,
                mfa_secret=plaintext_secret,
                mfa_backup_codes=list(legacy_codes),
            )
        )
        await db.commit()

    # TOTP login against the legacy plaintext secret
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
    )
    assert login.json().get("mfa_required") is True
    code = pyotp.TOTP(plaintext_secret).now()
    verify = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": code, "temp_token": login.json()["temp_token"]},
    )
    assert verify.status_code == 200, verify.text

    user = await _get_user_by_email(email)
    assert user.mfa_secret.startswith(AES_GCM_PREFIX)  # upgraded
    assert all(c.startswith("$2") for c in user.mfa_backup_codes or [])  # bcrypt

    # legacy backup code still verifies against the upgraded digests
    login2 = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "StrongPassword123!"},
    )
    backup_login = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": legacy_codes[0], "temp_token": login2.json()["temp_token"]},
    )
    assert backup_login.status_code == 200, backup_login.text
    user = await _get_user_by_email(email)
    assert len(user.mfa_backup_codes or []) == 1  # used code consumed


@pytest.mark.asyncio
async def test_new_backup_code_usable_through_the_api(client):
    """Codex r2 MF1 regression: 19-char backup codes must pass DTO
    validation and complete a real MFA login through the HTTP path."""
    import time as _time
    from datetime import datetime

    token = await _register_and_login(client, "mfa-bc@example.com", "mfa_bc_user")
    with _real_integration_access():
        setup = await client.post(
            "/api/v1/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"}
        )
    secret = setup.json()["secret"]
    backup_code = setup.json()["backup_codes"][0]
    assert len(backup_code) == 19  # XXXX-XXXX-XXXX-XXXX

    with _real_integration_access():
        enable = await client.post(
            "/api/v1/auth/mfa/verify",
            json={"code": pyotp.TOTP(secret).now()},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert enable.status_code == 200, enable.text

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": "mfa-bc@example.com", "password": "StrongPassword123!"},
    )
    temp_token = login.json()["temp_token"]

    # TOTP consumed the current window; the backup code bypasses TOTP anyway
    mfa_login = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": backup_code, "temp_token": temp_token},
    )
    assert mfa_login.status_code == 200, mfa_login.text
    assert mfa_login.json().get("token_type") == "bearer"


@pytest.mark.asyncio
async def test_concurrent_totp_claims_allow_exactly_one(client):
    """Two parallel verify-login calls with the same code: the conditional
    UPDATE must let exactly one through (Codex r1 MF2)."""
    import asyncio
    import time as _time
    from datetime import datetime

    from httpx import AsyncClient

    from app.core.database import AsyncSessionLocal
    from app.core.security import get_password_hash

    email = "mfa-race@example.com"
    secret = pyotp.random_base32()
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                username="mfa_race_user",
                hashed_password=get_password_hash("StrongPassword123!"),
                is_active=True,
                mfa_enabled=True,
                mfa_secret=secret,
                mfa_backup_codes=None,
            )
        )
        await db.commit()

    async with AsyncClient(app=app, base_url="http://test") as raw_client:
        tokens = []
        for _ in range(2):
            login = await raw_client.post(
                "/api/v1/auth/login",
                data={"username": email, "password": "StrongPassword123!"},
            )
            tokens.append(login.json()["temp_token"])
        code = pyotp.TOTP(secret).at(datetime.fromtimestamp((int(_time.time()) // 30 + 1) * 30))
        results = await asyncio.gather(
            *[
                raw_client.post(
                    "/api/v1/auth/mfa/verify-login",
                    json={"code": code, "temp_token": token},
                )
                for token in tokens
            ]
        )
    statuses = sorted(r.status_code for r in results)
    assert statuses[0] == 200, [r.text for r in results]
    assert all(s != 200 for s in statuses[1:]), statuses


def test_migration_038_downgrade_refuses_wave_b_data():
    """Downgrade must fail loudly when encrypted secrets / hashed codes
    exist instead of crashing halfway on PostgreSQL (Codex r1 MF5)."""
    import importlib.util
    from pathlib import Path

    from sqlalchemy import create_engine, text

    spec = importlib.util.spec_from_file_location(
        "m038",
        Path(__file__).parent.parent / "alembic" / "versions" / "038_add_mfa_security.py",
    )
    m038 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m038)

    class _Batch:
        def __enter__(self) -> "_Batch":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def drop_column(self, *a: object, **k: object) -> None:  # noqa: D401
            pass

        def alter_column(self, *a: object, **k: object) -> None:  # noqa: D401
            pass

    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        # alembic's `op` proxy only works inside a migration; stub it
        m038.op = SimpleNamespace(  # type: ignore[assignment]
            get_bind=lambda: conn,
            batch_alter_table=lambda table: _Batch(),
        )
        conn.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, mfa_secret TEXT, mfa_backup_codes TEXT, mfa_enabled BOOLEAN, mfa_last_used_counter INTEGER)"
            )
        )
        conn.execute(text("INSERT INTO users (mfa_secret) VALUES ('encgcm:AAAA')"))
        conn.commit()
        assert m038._wave_b_data_exists(conn) is True
        with pytest.raises(RuntimeError, match="Cannot downgrade"):
            m038.downgrade()
        # bcrypt digests alone must also block (legacy plaintext must not)
        conn.execute(text("UPDATE users SET mfa_secret = NULL"))
        conn.execute(text("UPDATE users SET mfa_backup_codes = '[\"$2b$12abc\"]'"))
        conn.commit()
        assert m038._wave_b_data_exists(conn) is True
        conn.execute(text("UPDATE users SET mfa_backup_codes = '[\"ABCD-1234\"]'"))
        conn.commit()
        assert m038._wave_b_data_exists(conn) is False  # legacy plaintext is fine
        m038.downgrade()  # runs through the stubbed batch ops
    engine.dispose()


def test_compose_proxy_trust_uses_literal_static_ip():
    """B3 config: uvicorn trusts a literal nginx IP (no CIDR support in
    ProxyHeadersMiddleware); nginx pins that address via ipam."""
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[2]
    nginx_ip = "172.28.0.2"
    for compose_name in ("docker-compose.yml", "docker-compose.pohelper.deploy.yml"):
        compose = yaml.safe_load((repo_root / compose_name).read_text())
        backend_cmd = compose["services"]["backend"]["command"]
        assert "--proxy-headers" in backend_cmd, compose_name
        assert (
            f"--forwarded-allow-ips=$${{UVICORN_FORWARDED_ALLOW_IPS:-{nginx_ip}}}" in backend_cmd
        ), (
            compose_name,
            backend_cmd,
        )
        # no CIDR trust left
        assert "172.16.0.0/12" not in backend_cmd
        networks = compose["networks"]["po_net"]["ipam"]["config"]
        assert any(cfg.get("subnet") == "172.28.0.0/24" for cfg in networks)
        frontend_nets = compose["services"]["frontend"]["networks"]
        assert frontend_nets["po_net"]["ipv4_address"] == nginx_ip
        # the frontend must share ONLY po_net with the backend: two shared
        # networks would let nginx reach backend via an untrusted source IP
        assert list(frontend_nets.keys()) == ["po_net"], (compose_name, frontend_nets)
        backend_nets = compose["services"]["backend"]["networks"]
        assert "po_net" in backend_nets, backend_nets


# ---------------------------------------------------------------------------
# B3: rate limiter storage + configured limits
# ---------------------------------------------------------------------------


def test_rate_limit_storage_falls_back_when_redis_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "REDIS_URL", "redis://127.0.0.1:6399/0")
    assert _resolve_storage_uri() is None


def test_configured_limits_parse():
    from limits import parse

    for value in (
        settings.RATE_LIMIT_DEFAULT,
        settings.RATE_LIMIT_AUTH,
        settings.RATE_LIMIT_SYNC,
    ):
        parse(value)  # raises on malformed strings


def test_rate_limits_wired_from_settings():
    """The login and sync limit decorators must carry the values configured
    in settings (RATE_LIMIT_AUTH / RATE_LIMIT_SYNC).

    NB: the limiter is read through the endpoint modules, not via
    `from app.core.rate_limit import limiter` - tests/test_traceability.py
    permanently swaps sys.modules["app.core.rate_limit"] with a no-op stub,
    while the decorators keep referencing the real limiter object.
    """
    from limits import parse as parse_limit

    from app.api.api_v1.endpoints import auth as auth_module
    from app.api.api_v1.endpoints import confluence as confluence_module
    from app.api.api_v1.endpoints import jira as jira_module

    real_limiters = {id(m.limiter) for m in (auth_module, jira_module, confluence_module)}
    assert len(real_limiters) == 1, "endpoint modules must share one limiter"

    registered = auth_module.limiter._route_limits

    def limits_of(route: str) -> list[str]:
        return [str(obj.limit) for obj in registered.get(route, [])]

    auth_expected = str(parse_limit(settings.RATE_LIMIT_AUTH))
    assert auth_expected in limits_of(f"{auth_module.__name__}.login")

    sync_expected = str(parse_limit(settings.RATE_LIMIT_SYNC))
    for route in (
        f"{jira_module.__name__}.sync_project_data",
        f"{confluence_module.__name__}.sync_confluence",
        f"{confluence_module.__name__}.sync_confluence_sse",
        f"{confluence_module.__name__}.start_celery_sync",
        f"{confluence_module.__name__}.sync_subtree",
    ):
        assert sync_expected in limits_of(route), route
