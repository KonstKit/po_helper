from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


def get_dialect_name(session: AsyncSession) -> str:
    """Return SQLAlchemy dialect name for the given session.

    Falls back to 'unknown' if it cannot be determined.
    """
    try:
        bind = session.get_bind()  # type: ignore[attr-defined]
        if bind is not None and getattr(bind, "dialect", None) is not None:
            return bind.dialect.name or "unknown"
    except Exception:
        pass
    # Older SQLAlchemy versions may expose .bind
    try:
        bind = getattr(session, "bind", None)
        if bind is not None and getattr(bind, "dialect", None) is not None:
            return bind.dialect.name or "unknown"
    except Exception:
        pass
    return "unknown"


def supports_for_update(session: AsyncSession) -> bool:
    """Best-effort check whether the current dialect supports FOR UPDATE.

    SQLite does not support it; most others (PostgreSQL/MySQL) do.
    """
    name = get_dialect_name(session)
    return name not in ("sqlite", "unknown")

