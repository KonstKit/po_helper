from __future__ import annotations

from typing import Any, Dict

from app.core.crypto import (
    decrypt_str_with_metadata,
    encrypt_str,
    has_dedicated_encryption_secret,
    is_encrypted,
)

SECRET_KEYS = {
    "token",
    "api_token",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "api_secret",
    "client_secret",
    "private_key",
}


def _normalize_settings(settings_json: Any) -> Any:
    if settings_json is None:
        return {}
    if isinstance(settings_json, dict):
        return settings_json
    if isinstance(settings_json, list):
        return settings_json
    return {}


def _looks_like_secret_key(key: str) -> bool:
    key_lower = key.strip().lower()
    return any(secret_key in key_lower for secret_key in SECRET_KEYS)


def _decrypt_value(value: Any, key: str | None = None) -> tuple[Any, bool]:
    if not isinstance(value, dict):
        if isinstance(value, str):
            if is_encrypted(value):
                decrypted, legacy = decrypt_str_with_metadata(value)
                if decrypted is not None:
                    return decrypted, legacy
                return value, False
            if key and _looks_like_secret_key(key) and value:
                return value, True
            return value, False
        if isinstance(value, list):
            items, needs_reencrypt = [], False
            for item in value:
                item_value, item_needs_reencrypt = _decrypt_value(item, key=key)
                items.append(item_value)
                needs_reencrypt = needs_reencrypt or item_needs_reencrypt
            return items, needs_reencrypt
        return value, False

    result: Dict[str, Any] = {}
    needs_reencrypt = False
    for nested_key, nested_value in value.items():
        nested, nested_needs_reencrypt = _decrypt_value(nested_value, key=nested_key)
        result[nested_key] = nested
        needs_reencrypt = needs_reencrypt or nested_needs_reencrypt
    return result, needs_reencrypt


def _encrypt_value(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            inner_key: _encrypt_value(inner_value, key=inner_key)
            for inner_key, inner_value in value.items()
        }
    if isinstance(value, list):
        return [_encrypt_value(item, key=key) for item in value]
    if isinstance(value, str) and key and _looks_like_secret_key(key) and value:
        # encrypt_str raises RuntimeError when no secret is configured (B5);
        # callers translate it into an explicit API error instead of
        # silently persisting plaintext.
        return encrypt_str(value)
    return value


def _redact_value(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            inner_key: _redact_value(inner_value, key=inner_key)
            for inner_key, inner_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, key=key) for item in value]
    if isinstance(value, str) and key and _looks_like_secret_key(key):
        return "********"
    if isinstance(value, str) and is_encrypted(value):
        return "********"
    return value


def decrypt_connector_settings(settings_json: Dict[str, Any] | list | None) -> tuple[Any, bool]:
    parsed = _normalize_settings(settings_json)
    decrypted, needs_reencrypt = _decrypt_value(parsed)
    return decrypted, bool(needs_reencrypt)


def encrypt_connector_settings(settings_json: Dict[str, Any] | list | None) -> Any:
    parsed = _normalize_settings(settings_json)
    return _encrypt_value(parsed)


def redact_connector_settings(settings_json: Dict[str, Any] | list | None) -> Any:
    parsed = _normalize_settings(settings_json)
    return _redact_value(parsed)


def settings_have_secrets(settings_json: Dict[str, Any] | list | None) -> bool:
    parsed = _normalize_settings(settings_json)
    stack = [parsed]
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for item_key, item_value in value.items():
                if _looks_like_secret_key(item_key) and isinstance(item_value, str) and item_value:
                    return True
                if isinstance(item_value, (dict, list)):
                    stack.append(item_value)
        elif isinstance(value, list):
            stack.extend(value)
    return False
