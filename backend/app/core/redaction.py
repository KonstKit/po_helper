from __future__ import annotations

from typing import Dict, Mapping


_SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-auth-token",
    "cookie",
    "set-cookie",
}


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    redacted: Dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() in _SENSITIVE_HEADER_KEYS:
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted
