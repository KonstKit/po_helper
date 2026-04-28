import binascii
import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

AES_GCM_PREFIX = "encgcm:"
LEGACY_FERNET_PREFIX = "enc:"
BASE64_DECODE_ERRORS = (binascii.Error, ValueError, TypeError)
AES_DECRYPTION_ERRORS = (InvalidTag, ValueError, TypeError, UnicodeDecodeError)
FERNET_DECRYPTION_ERRORS = (InvalidToken, ValueError, TypeError, UnicodeDecodeError)


def has_dedicated_encryption_secret() -> bool:
    return settings.has_dedicated_encryption_secret


def _iter_encryption_secrets(include_legacy: bool = True) -> list[str]:
    secrets: list[str] = []
    if settings.ENCRYPTION_SECRET:
        secrets.append(settings.ENCRYPTION_SECRET)
    if getattr(settings, "ENCRYPTION_SECRET_PREVIOUS", None):
        secrets.extend([s for s in settings.ENCRYPTION_SECRET_PREVIOUS if s])
    if include_legacy and settings.SECRET_KEY and settings.SECRET_KEY not in secrets:
        secrets.append(settings.SECRET_KEY)
    return secrets


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


def is_encrypted(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.startswith(AES_GCM_PREFIX) or value.startswith(LEGACY_FERNET_PREFIX)


def decrypt_str_with_metadata(ciphertext: Optional[str]) -> tuple[Optional[str], bool]:
    if not ciphertext:
        return None, False

    if not is_encrypted(ciphertext):
        return ciphertext, True

    current_secret = settings.ENCRYPTION_SECRET or settings.SECRET_KEY
    if ciphertext.startswith(AES_GCM_PREFIX):
        token = ciphertext[len(AES_GCM_PREFIX) :]
        try:
            data = base64.urlsafe_b64decode(token.encode("utf-8"))
        except BASE64_DECODE_ERRORS:
            return None, False
        nonce, encrypted = data[:12], data[12:]

        if current_secret:
            try:
                aesgcm = AESGCM(_derive_key(current_secret))
                plaintext = aesgcm.decrypt(nonce, encrypted, associated_data=None)
                return plaintext.decode("utf-8"), False
            except AES_DECRYPTION_ERRORS:
                pass

        for secret in _iter_encryption_secrets(include_legacy=True):
            if current_secret and secret == current_secret:
                continue
            try:
                aesgcm = AESGCM(_derive_key(secret))
                plaintext = aesgcm.decrypt(nonce, encrypted, associated_data=None)
                return plaintext.decode("utf-8"), True
            except AES_DECRYPTION_ERRORS:
                continue
        return None, False

    if ciphertext.startswith(LEGACY_FERNET_PREFIX):
        token = ciphertext[len(LEGACY_FERNET_PREFIX) :]
        if current_secret:
            try:
                fernet = Fernet(base64.urlsafe_b64encode(_derive_key(current_secret)))
                return fernet.decrypt(token.encode("utf-8")).decode("utf-8"), False
            except FERNET_DECRYPTION_ERRORS:
                pass
        for secret in _iter_encryption_secrets(include_legacy=True):
            if current_secret and secret == current_secret:
                continue
            try:
                fernet = Fernet(base64.urlsafe_b64encode(_derive_key(secret)))
                return fernet.decrypt(token.encode("utf-8")).decode("utf-8"), True
            except FERNET_DECRYPTION_ERRORS:
                continue
        return None, False

    return None, False


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


def encrypt_integration_secret(plaintext: Optional[str]) -> Optional[str]:
    if not plaintext:
        return None
    if not has_dedicated_encryption_secret():
        raise RuntimeError(
            "A dedicated ENCRYPTION_SECRET is required to persist Jira/Confluence tokens."
        )

    secret = settings.ENCRYPTION_SECRET
    if not secret:
        raise RuntimeError(
            "A dedicated ENCRYPTION_SECRET is required to persist Jira/Confluence tokens."
        )

    aesgcm = AESGCM(_derive_key(secret))
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    token = base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")
    return f"{AES_GCM_PREFIX}{token}"


def decrypt_str(ciphertext: Optional[str]) -> Optional[str]:
    if not ciphertext:
        return None

    if ciphertext.startswith(AES_GCM_PREFIX):
        token = ciphertext[len(AES_GCM_PREFIX) :]
        try:
            data = base64.urlsafe_b64decode(token.encode("utf-8"))
        except BASE64_DECODE_ERRORS:
            return None
        nonce, encrypted = data[:12], data[12:]
        for secret in _iter_encryption_secrets(include_legacy=True):
            try:
                aesgcm = AESGCM(_derive_key(secret))
                plaintext = aesgcm.decrypt(nonce, encrypted, associated_data=None)
                return plaintext.decode("utf-8")
            except AES_DECRYPTION_ERRORS:
                continue
        return None

    if ciphertext.startswith(LEGACY_FERNET_PREFIX):
        token = ciphertext[len(LEGACY_FERNET_PREFIX) :]
        for secret in _iter_encryption_secrets(include_legacy=True):
            try:
                fernet = Fernet(base64.urlsafe_b64encode(_derive_key(secret)))
                return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
            except FERNET_DECRYPTION_ERRORS:
                continue
        return None

    return ciphertext
