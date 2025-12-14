import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

AES_GCM_PREFIX = "encgcm:"
LEGACY_FERNET_PREFIX = "enc:"


def _derive_key(secret: str) -> bytes:
    """Derive a 32-byte key from the configured secret."""
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _get_aesgcm() -> Optional[AESGCM]:
    secret = settings.ENCRYPTION_SECRET or settings.SECRET_KEY
    if not secret:
        return None
    return AESGCM(_derive_key(secret))


def _get_legacy_fernet() -> Optional[Fernet]:
    secret = settings.ENCRYPTION_SECRET or settings.SECRET_KEY
    if not secret:
        return None
    return Fernet(base64.urlsafe_b64encode(_derive_key(secret)))


def encrypt_str(plaintext: Optional[str]) -> Optional[str]:
    if not plaintext:
        return None
    aesgcm = _get_aesgcm()
    if not aesgcm:
        return plaintext
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")
    return f"{AES_GCM_PREFIX}{token}"


def decrypt_str(ciphertext: Optional[str]) -> Optional[str]:
    if not ciphertext:
        return None

    if ciphertext.startswith(AES_GCM_PREFIX):
        token = ciphertext[len(AES_GCM_PREFIX):]
        try:
            data = base64.urlsafe_b64decode(token.encode("utf-8"))
            nonce, encrypted = data[:12], data[12:]
            aesgcm = _get_aesgcm()
            if not aesgcm:
                return None
            plaintext = aesgcm.decrypt(nonce, encrypted, associated_data=None)
            return plaintext.decode("utf-8")
        except Exception:
            return None

    if ciphertext.startswith(LEGACY_FERNET_PREFIX):
        token = ciphertext[len(LEGACY_FERNET_PREFIX):]
        try:
            fernet = _get_legacy_fernet()
            if not fernet:
                return None
            return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, Exception):
            return None

    return ciphertext
