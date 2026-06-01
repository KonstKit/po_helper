import base64
import hashlib

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import LEGACY_FERNET_PREFIX, decrypt_str, decrypt_str_with_metadata
from app.models.settings import IntegrationSetting
from app.services.integration_secrets import load_integration_token


@pytest.mark.asyncio
async def test_load_integration_token_reencrypts_legacy_ciphertext(db_session, monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret-key-1234567890abcdef")
    monkeypatch.setattr(
        settings,
        "ENCRYPTION_SECRET",
        "dedicated-encryption-secret-1234567890abcdef",
    )

    legacy_key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    legacy_fernet = Fernet(base64.urlsafe_b64encode(legacy_key))
    legacy_token = legacy_fernet.encrypt(b"legacy-jira-token").decode("utf-8")
    wrapped = f"{LEGACY_FERNET_PREFIX}{legacy_token}"

    row = IntegrationSetting(
        kind="jira",
        base_url="https://example.atlassian.net",
        email="user@example.com",
        api_token=wrapped,
    )
    db_session.add(row)
    await db_session.commit()

    loaded = await load_integration_token(db_session, row)

    refreshed = (
        await db_session.execute(select(IntegrationSetting).where(IntegrationSetting.id == row.id))
    ).scalar_one()

    assert loaded == "legacy-jira-token"
    assert refreshed.api_token != wrapped
    assert decrypt_str(refreshed.api_token) == "legacy-jira-token"
    assert decrypt_str_with_metadata(refreshed.api_token) == ("legacy-jira-token", False)
