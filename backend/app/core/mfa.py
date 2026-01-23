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
from typing import Optional, Tuple
from dataclasses import dataclass

import pyotp
import qrcode
from qrcode.image.pure import PyPNGImage

from app.core.config import settings

logger = logging.getLogger(__name__)

# Constants
TOTP_INTERVAL = 30  # seconds
TOTP_DIGITS = 6
BACKUP_CODE_LENGTH = 8
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
        # Generate alphanumeric codes (easier to type than pure hex)
        code = secrets.token_hex(BACKUP_CODE_LENGTH // 2).upper()
        # Format as XXXX-XXXX for readability
        formatted = f"{code[:4]}-{code[4:]}"
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


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a TOTP code against the secret.

    Args:
        secret: User's TOTP secret
        code: 6-digit code from authenticator app

    Returns:
        True if code is valid
    """
    if not secret or not code:
        return False

    # Clean up code (remove spaces, dashes)
    code = code.replace(" ", "").replace("-", "")

    if len(code) != TOTP_DIGITS or not code.isdigit():
        return False

    totp = pyotp.TOTP(secret)

    # Allow 1 time window before/after for clock skew
    return totp.verify(code, valid_window=1)


def verify_backup_code(code: str, stored_codes: list[str]) -> Tuple[bool, Optional[int]]:
    """
    Verify a backup code and return index if valid.

    Args:
        code: Backup code entered by user
        stored_codes: List of remaining backup codes

    Returns:
        Tuple of (is_valid, index_to_remove)
    """
    if not code or not stored_codes:
        return False, None

    # Normalize code
    code = code.upper().replace(" ", "").replace("-", "")

    for idx, stored_code in enumerate(stored_codes):
        stored_normalized = stored_code.upper().replace("-", "")
        if secrets.compare_digest(code, stored_normalized):
            return True, idx

    return False, None


def hash_backup_codes(codes: list[str]) -> list[str]:
    """
    Hash backup codes for secure storage.

    Note: In production, you might want to use bcrypt/argon2 for these.
    For simplicity, we store them as-is but compare securely.

    Args:
        codes: Plain backup codes

    Returns:
        Codes suitable for storage (currently just the codes)
    """
    # For now, we store codes directly but use constant-time comparison
    # In production, consider hashing each code individually
    return codes


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
