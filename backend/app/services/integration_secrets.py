from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt_str_with_metadata, encrypt_integration_secret
from app.models.settings import IntegrationSetting
from app.utils import transactional_session

logger = logging.getLogger(__name__)


async def load_integration_token(
    db: AsyncSession,
    row: IntegrationSetting | None,
) -> Optional[str]:
    """Load a Jira/Confluence token and softly migrate legacy ciphertext when possible."""
    if row is None or not row.api_token:
        return None

    token, needs_reencrypt = decrypt_str_with_metadata(row.api_token)
    if token is None:
        return None

    if needs_reencrypt:
        await maybe_reencrypt_integration_token(db, row, token)

    return token


async def maybe_reencrypt_integration_token(
    db: AsyncSession,
    row: IntegrationSetting,
    token: str,
) -> bool:
    """Best-effort migration to the dedicated ENCRYPTION_SECRET."""
    if not token:
        return False

    try:
        encrypted = encrypt_integration_secret(token)
    except RuntimeError:
        return False
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to prepare migrated %s integration token: %s", row.kind, exc)
        return False

    if not encrypted or encrypted == row.api_token:
        return False

    try:
        async with transactional_session(db):
            row.api_token = encrypted
        logger.info(
            "Re-encrypted legacy %s integration token with dedicated ENCRYPTION_SECRET",
            row.kind,
        )
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to persist migrated %s integration token: %s", row.kind, exc)
        return False
