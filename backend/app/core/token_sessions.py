import hashlib
import secrets

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.token_session import TokenSession

REFRESH_TOKEN_BYTES = 32
"""Length of the opaque refresh token (256 bits of entropy)."""


def _hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest: the plaintext token is never stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_refresh_token() -> tuple[str, str]:
    """Generate an opaque refresh token; return (plaintext, stored_hash)."""
    token = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    return token, _hash_refresh_token(token)


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


async def create_token_session(
    db: AsyncSession,
    *,
    user_id: int,
    refresh_token: str,
    user_agent: str | None = None,
) -> TokenSession:
    """Persist a new server-side session for the issued refresh token."""
    session = TokenSession(
        user_id=user_id,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        expires_at=refresh_token_expiry(),
    )
    if user_agent:
        session.user_agent = user_agent
    db.add(session)
    await db.flush()
    return session


async def get_active_session_by_token(db: AsyncSession, refresh_token: str) -> TokenSession | None:
    """Return the live (unrevoked, unexpired) session for a refresh token."""
    token_hash = _hash_refresh_token(refresh_token)
    cutoff = datetime.now(timezone.utc)
    result = await db.execute(
        select(TokenSession).where(
            TokenSession.refresh_token_hash == token_hash,
            TokenSession.revoked_at.is_(None),
            cutoff < TokenSession.expires_at,
        )
    )
    return result.scalar_one_or_none()


async def get_session_by_token_any_state(
    db: AsyncSession, refresh_token: str
) -> TokenSession | None:
    """Look a token up regardless of revocation/expiry (reuse triage)."""
    result = await db.execute(
        select(TokenSession).where(
            TokenSession.refresh_token_hash == _hash_refresh_token(refresh_token)
        )
    )
    return result.scalar_one_or_none()


async def revoke_session(db: AsyncSession, session: TokenSession) -> None:
    """Revoke one session (idempotent)."""
    if session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        await db.flush()


async def revoke_all_user_sessions(db: AsyncSession, user_id: int) -> int:
    """Revoke every live session of a user (password change, logout everywhere)."""
    result = await db.execute(
        select(TokenSession).where(
            TokenSession.user_id == user_id,
            TokenSession.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    count = 0
    for session in result.scalars():
        session.revoked_at = now
        count += 1
    if count:
        await db.flush()
    return count
