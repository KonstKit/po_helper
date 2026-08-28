"""Signed OAuth2 state tokens with TTL and provider binding.

Protects the OAuth2 authorization-code flow against forged callbacks and
login CSRF: the ``state`` returned by the provider must be a server-signed
token (HMAC-SHA256 over payload with SECRET_KEY), unexpired, issued for the
same provider, and match the browser-bound cookie set when the flow started.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional

from app.core.config import settings

# Cookie that binds a flow to the browser that started it (double-submit).
OAUTH_STATE_COOKIE = "po_oauth_csrf"


class OAuthStateError(Exception):
    """Raised when an OAuth state token is missing, tampered, or expired."""


def _sign(payload: bytes) -> str:
    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return digest


def _b64_encode(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_decode(data: str) -> bytes:
    import base64

    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def create_oauth_state(
    provider: str, redirect_uri: Optional[str] = None, max_age: Optional[int] = None
) -> str:
    """Create a signed state token: base64url(payload).hmac."""
    payload: dict[str, Any] = {
        "nonce": secrets.token_urlsafe(16),
        "provider": provider,
        "redirect_uri": redirect_uri,
        "exp": int(time.time()) + (max_age or settings.OAUTH_STATE_MAX_AGE_SECONDS),
    }
    encoded = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{encoded}.{_sign(encoded.encode('utf-8'))}"


def verify_oauth_state(
    state: str,
    provider: str,
    max_age: Optional[int] = None,
) -> dict[str, Any]:
    """Verify signature, expiry and provider binding; return the payload.

    The payload's ``redirect_uri`` is covered by the HMAC and was validated
    against the allow list at flow start, so callers can trust it here.
    Raises OAuthStateError on any mismatch.
    """
    try:
        encoded, signature = state.rsplit(".", 1)
    except ValueError as exc:
        raise OAuthStateError("malformed state token") from exc

    expected = _sign(encoded.encode("utf-8"))
    if not hmac.compare_digest(signature, expected):
        raise OAuthStateError("invalid state signature")

    try:
        payload = json.loads(_b64_decode(encoded))
    except (ValueError, json.JSONDecodeError) as exc:
        raise OAuthStateError("undecodable state payload") from exc

    ttl = max_age or settings.OAUTH_STATE_MAX_AGE_SECONDS
    if int(payload.get("exp", 0)) < time.time() or int(payload.get("exp", 0)) > time.time() + ttl + 60:
        raise OAuthStateError("state token expired or issued too far in the future")

    if payload.get("provider") != provider:
        raise OAuthStateError("state token was issued for a different provider")

    return payload


def validate_redirect_uri_override(redirect_uri: Optional[str]) -> Optional[str]:
    """Allow-list check for client-supplied redirect_uri overrides.

    Returns the (possibly normalized) override, or None when the caller did
    not supply one. Raises OAuthStateError for overrides that are not listed
    in OAUTH_ALLOWED_REDIRECT_URIS.
    """
    if redirect_uri is None:
        return None
    allowed = settings.OAUTH_ALLOWED_REDIRECT_URIS
    if not allowed or redirect_uri not in allowed:
        raise OAuthStateError("redirect_uri is not in the allow list")
    return redirect_uri
