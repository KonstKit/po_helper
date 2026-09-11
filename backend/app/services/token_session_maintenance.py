from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_

from app.models.token_session import TokenSession


async def prune_token_sessions(
    db,
    *,
    revoked_before: datetime,
    expired_before: datetime,
) -> int:
    """Delete dead sessions: expired, or revoked longer than the grace."""
    result = await db.execute(
        delete(TokenSession).where(
            or_(
                TokenSession.expires_at < expired_before,
                TokenSession.revoked_at.is_not(None) & (TokenSession.revoked_at < revoked_before),
            )
        )
    )
    return result.rowcount or 0
