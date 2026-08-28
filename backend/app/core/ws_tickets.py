"""One-time tickets for WebSocket authentication.

Browsers cannot send an Authorization header during a WebSocket handshake,
so the client first obtains a short-lived single-use ticket over an
authenticated HTTP call and passes only that ticket in the WS query string.
The user's JWT never appears in a URL (proxy/access logs, DevTools).

In-memory by design: every deployment in this repo runs uvicorn as a
single process. Switch to Redis SETNX if horizontal scaling is added.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Dict, Tuple

_WS_TICKET_TTL_SECONDS = 60

_lock = threading.Lock()
_tickets: Dict[str, Tuple[str, float]] = {}


def _sweep(now: float) -> None:
    for ticket in [t for t, (_, exp) in _tickets.items() if exp < now]:
        _tickets.pop(ticket, None)


def issue_ws_ticket(user_email: str) -> str:
    """Create a single-use ticket bound to the user (call after JWT auth)."""
    ticket = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        _sweep(now)
        _tickets[ticket] = (user_email, now + _WS_TICKET_TTL_SECONDS)
    return ticket


def consume_ws_ticket(ticket: str) -> str | None:
    """Atomically consume a ticket; returns the user email exactly once."""
    with _lock:
        entry = _tickets.pop(ticket, None)
    if entry is None:
        return None
    email, expires_at = entry
    if expires_at < time.time():
        return None
    return email
