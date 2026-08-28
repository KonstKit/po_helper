"""Wave A regression tests from the Should Fix roadmap (docs/SHOULD_FIX_ROADMAP.md).

A1: the placeholder SECRET_KEY must be refused in staging/production.
A2: MFA verify-login takes the mfa_pending token in the body, not the query.
A5: migration 037 creates the four missing FK indexes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.main import _validate_runtime_security_settings


# ---------------------------------------------------------------------------
# A1: placeholder SECRET_KEY guard
# ---------------------------------------------------------------------------


def test_placeholder_secret_key_refused_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", settings.SECRET_KEY_PLACEHOLDER)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _validate_runtime_security_settings()


def test_placeholder_secret_key_refused_in_staging(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    monkeypatch.setattr(settings, "SECRET_KEY", settings.SECRET_KEY_PLACEHOLDER)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _validate_runtime_security_settings()


def test_placeholder_secret_key_allowed_in_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "SECRET_KEY", settings.SECRET_KEY_PLACEHOLDER)
    _validate_runtime_security_settings()  # must not raise on the placeholder alone


# ---------------------------------------------------------------------------
# A2: MFA temp_token in body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mfa_verify_login_temp_token_in_body_not_query(client):
    """The mfa_pending token must be read from the JSON body; a query-string
    token must no longer be honored (it leaks into proxy/access logs)."""
    response = await client.post(
        "/api/v1/auth/mfa/verify-login?temp_token=leaked-to-logs",
        json={"code": "123456"},
    )
    # Unauthenticated code path: the query param must be ignored entirely -
    # FastAPI would 422 if the query param were still declared; without it
    # the missing body temp_token yields a validation error (422).
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("temp_token" in str(item.get("loc", [])) for item in detail), detail


@pytest.mark.asyncio
async def test_mfa_verify_login_body_token_reaches_decode(client):
    """Positive body path: the temp_token from the JSON body is the one the
    endpoint decodes - a syntactically valid JWT with the wrong type fails
    with the decode-stage error, proving the body field was consumed."""
    from app.core.security import create_access_token

    wrong_type_token = create_access_token({"sub": "x@example.com"})
    response = await client.post(
        "/api/v1/auth/mfa/verify-login",
        json={"code": "123456", "temp_token": wrong_type_token},
    )
    # token decodes but lacks type=mfa_pending; the broad except wraps the
    # 400 into the generic 401 decode-stage response
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired temporary token"


# ---------------------------------------------------------------------------
# A5: FK indexes migration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fk_indexes_exist(db_session):
    expected = {
        "ix_legacy_mappings_new_artifact_id",
        "ix_suggested_links_from_artifact_id",
        "ix_suggested_links_to_artifact_id",
        "ix_artifacts_parent_version_id",
    }
    result = await db_session.execute(
        text("SELECT name FROM sqlite_master WHERE type='index'")
    )
    existing = {row[0] for row in result}
    missing = expected - existing
    assert not missing, f"missing FK indexes: {missing} (create_all must reflect migration 037)"
