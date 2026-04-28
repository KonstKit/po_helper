import base64
import hashlib
import os

import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.config import settings


def test_encrypt_str_sets_aes_gcm_prefix():
    plaintext = "super-secret-value"
    token = crypto.encrypt_str(plaintext)
    assert token is not None
    assert token.startswith(crypto.AES_GCM_PREFIX)
    assert crypto.decrypt_str(token) == plaintext


def test_decrypt_str_supports_legacy_tokens():
    secret = os.environ["SECRET_KEY"]
    key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    legacy_token = Fernet(fernet_key).encrypt(b"legacy-secret").decode("utf-8")
    wrapped = f"{crypto.LEGACY_FERNET_PREFIX}{legacy_token}"

    assert crypto.decrypt_str(wrapped) == "legacy-secret"


def test_decrypt_str_returns_none_for_bad_ciphertext():
    assert crypto.decrypt_str("encgcm:not-valid") is None


def test_encrypt_integration_secret_requires_dedicated_secret(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", None)

    with pytest.raises(RuntimeError, match="dedicated ENCRYPTION_SECRET"):
        crypto.encrypt_integration_secret("integration-token")


def test_encrypt_integration_secret_round_trips_with_dedicated_secret(monkeypatch):
    monkeypatch.setattr(settings, "SECRET_KEY", "shared-secret")
    monkeypatch.setattr(settings, "ENCRYPTION_SECRET", "dedicated-secret")

    token = crypto.encrypt_integration_secret("integration-token")

    assert token is not None
    assert token.startswith(crypto.AES_GCM_PREFIX)
    assert crypto.decrypt_str(token) == "integration-token"
