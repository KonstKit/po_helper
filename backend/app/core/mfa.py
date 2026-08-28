"""
Multi-Factor Authentication (MFA) with TOTP support.

Provides TOTP-based MFA implementation compatible with:
- Google Authenticator
- Microsoft Authenticator
- Authy
- 1Password
- Any RFC 6238 TOTP app
"""

import base64
import io
import logging
import secrets
import time
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass

import pyotp
import qrcode
from qrcode.image.pure import PyPNGImage

from app.core.config import settings
from app.core.crypto import (
    AES_GCM_PREFIX,
    decrypt_str,
    encrypt_integration_secret,
)

logger = logging.getLogger(__name__)

# Constants
TOTP_INTERVAL = 30  # seconds
TOTP_DIGITS = 6
# 16 hex chars = 64 bits of entropy: with a slow per-code KDF (bcrypt) this
# makes offline brute-force of a leaked digest infeasible (32-bit codes of
# the old format were brute-forceable despite hashing).
BACKUP_CODE_LENGTH = 16
BACKUP_CODE_COUNT = 10


class MFAError(Exception):
    """Raised when MFA operation fails."""

    def __init__(self, error: str, description: str = ""):
        self.error = error
        self.description = description
        super().__init__(f"{error}: {description}" if description else error)


@dataclass
class MFASetupData:
    """Data returned during MFA setup process."""

    secret: str
    provisioning_uri: str
    qr_code_base64: str
    backup_codes: list[str]


def generate_totp_secret() -> str:
    """Generate a random TOTP secret."""
    return pyotp.random_base32()


def generate_backup_codes(count: int = BACKUP_CODE_COUNT) -> list[str]:
    """
    Generate backup recovery codes.

    These codes can be used if the user loses access to their authenticator app.
    Each code can only be used once.
    """
    codes = []
    for _ in range(count):
        code = secrets.token_hex(BACKUP_CODE_LENGTH // 2).upper()
        # Format as XXXX-XXXX-XXXX-XXXX for readability
        formatted = "-".join(code[i : i + 4] for i in range(0, len(code), 4))
        codes.append(formatted)
    return codes


def get_provisioning_uri(secret: str, email: str, issuer: Optional[str] = None) -> str:
    """
    Generate TOTP provisioning URI for QR code.

    Args:
        secret: TOTP secret key
        email: User's email address
        issuer: App name (defaults to settings)

    Returns:
        otpauth:// URI for authenticator apps
    """
    issuer = issuer or getattr(settings, "APP_NAME", "PO Helper")
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


def generate_qr_code_base64(provisioning_uri: str) -> str:
    """
    Generate QR code as base64-encoded PNG.

    Args:
        provisioning_uri: otpauth:// URI

    Returns:
        Base64-encoded PNG image data
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    # Create image
    img = qr.make_image(image_factory=PyPNGImage)

    # Convert to base64
    buffer = io.BytesIO()
    img.save(buffer)
    buffer.seek(0)
    img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return f"data:image/png;base64,{img_base64}"


def setup_mfa(email: str) -> MFASetupData:
    """
    Initialize MFA setup for a user.

    Args:
        email: User's email address

    Returns:
        MFASetupData with secret, QR code, and backup codes
    """
    secret = generate_totp_secret()
    provisioning_uri = get_provisioning_uri(secret, email)
    qr_code = generate_qr_code_base64(provisioning_uri)
    backup_codes = generate_backup_codes()

    return MFASetupData(
        secret=secret,
        provisioning_uri=provisioning_uri,
        qr_code_base64=qr_code,
        backup_codes=backup_codes,
    )


def _normalize_totp_code(code: str) -> str:
    return code.replace(" ", "").replace("-", "")


def verify_totp_with_counter(secret: str, code: str) -> Optional[int]:
    """Verify a TOTP code and return the matched time interval counter.

    Accepts the same +/-1 window as before (clock skew), but returns the
    counter of the interval that matched so callers can reject replayed
    codes (anti-replay) instead of accepting the same code for ~90s.
    Returns None when the code is invalid.
    """
    if not secret or not code:
        return None

    code = _normalize_totp_code(code)
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None

    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset_seconds in (-TOTP_INTERVAL, 0, TOTP_INTERVAL):
        moment = now + offset_seconds
        if totp.verify(code, for_time=datetime.fromtimestamp(moment)):
            return moment // TOTP_INTERVAL
    return None


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a TOTP code against the secret (window +/-1 for clock skew).

    Prefer verify_totp_with_counter + a last-used check: this helper
    accepts a replayed code within its validity window.
    """
    return verify_totp_with_counter(secret, code) is not None


def _normalize_backup_code(code: str) -> str:
    return code.upper().replace(" ", "").replace("-", "")


def _is_kdf_backup_code(entry: str) -> bool:
    """bcrypt digests start with $2 (passlib emits $2b$...)."""
    return entry.startswith("$2")


def hash_backup_code(code: str) -> str:
    """bcrypt digest of a normalized backup code (slow KDF, safe at rest).

    Codes carry 64 bits of entropy and are shown once, but a leaked digest
    must still resist offline brute-force - hence a memory-hard KDF rather
    than a fast digest like SHA-256. Uses the bcrypt package directly:
    passlib 1.7.4 is incompatible with bcrypt>=4.1 at runtime.
    """
    import bcrypt as _bcrypt

    return _bcrypt.hashpw(_normalize_backup_code(code).encode("utf-8"), _bcrypt.gensalt()).decode(
        "ascii"
    )


def _verify_kdf_backup_code(candidate: str, stored: str) -> bool:
    import bcrypt as _bcrypt

    try:
        return _bcrypt.checkpw(
            _normalize_backup_code(candidate).encode("utf-8"),
            stored.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def verify_backup_code(code: str, stored_codes: list[str]) -> Tuple[bool, Optional[int]]:
    """
    Verify a backup code and return index if valid.

    Stored entries are bcrypt digests (see hash_backup_codes); entries
    written before hashing was introduced are matched as legacy plaintext
    and should be upgraded by the caller (see auth._upgrade_mfa_storage).
    """
    if not code or not stored_codes:
        return False, None

    candidate = _normalize_backup_code(code)

    for idx, stored_code in enumerate(stored_codes):
        if _is_kdf_backup_code(stored_code):
            if _verify_kdf_backup_code(candidate, stored_code):
                return True, idx
        else:
            legacy_normalized = _normalize_backup_code(stored_code)
            if secrets.compare_digest(candidate, legacy_normalized):
                return True, idx

    return False, None


def hash_backup_codes(codes: list[str]) -> list[str]:
    """
    Hash backup codes for secure storage (bcrypt per code).

    Codes are single-use random values shown to the user once; the slow KDF
    exists for the leaked-database scenario, online use is already gated by
    one-time consumption and endpoint rate limits.
    """
    return [hash_backup_code(code) for code in codes]


def encrypt_mfa_secret(secret: str) -> str:
    """Encrypt a TOTP secret for at-rest storage (AES-GCM, ENCRYPTION_SECRET)."""
    encrypted = encrypt_integration_secret(secret)
    assert encrypted is not None
    return encrypted


def decrypt_mfa_secret(stored: str) -> str:
    """Decrypt a stored TOTP secret.

    Values without the encrypted prefix are pre-encryption plaintext
    (written before wave B); callers upgrade them via re-encryption.
    """
    if stored.startswith(AES_GCM_PREFIX):
        decrypted = decrypt_str(stored)
        if decrypted is None:
            raise MFAError("secret_decryption_failed", "Stored MFA secret could not be decrypted")
        return decrypted
    return stored


def get_current_totp(secret: str) -> str:
    """
    Get the current TOTP code (useful for testing).

    Args:
        secret: TOTP secret

    Returns:
        Current 6-digit code
    """
    totp = pyotp.TOTP(secret)
    return totp.now()


def remaining_time_in_period() -> int:
    """
    Get remaining seconds in current TOTP period.

    Returns:
        Seconds until next code
    """
    import time

    return TOTP_INTERVAL - (int(time.time()) % TOTP_INTERVAL)
