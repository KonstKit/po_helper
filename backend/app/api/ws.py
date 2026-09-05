from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.api.deps import _resolve_current_user
from app.core.database import AsyncSessionLocal
from app.core.notifications import connections
from app.core.ws_tickets import consume_ws_ticket
from app.models import User


router = APIRouter()


async def _resolve_ws_user(ws: WebSocket) -> User | None:
    """Authenticate the handshake via a one-time ticket or a Bearer header.

    The long-lived JWT is deliberately NOT accepted as a query parameter:
    query strings end up in proxy/access logs. Browsers obtain a
    single-use ticket from POST /auth/ws-ticket instead.
    """
    ticket = ws.query_params.get("ticket")
    if ticket:
        email = consume_ws_ticket(ticket)
        if not email:
            return None
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()

    header = ws.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        async with AsyncSessionLocal() as db:
            try:
                return await _resolve_current_user(
                    db,
                    request=ws,
                    authorization=header,
                    allow_debug_demo_fallback=False,
                )
            except Exception:
                return None
    return None


@router.websocket("/ws")
async def websocket_updates(ws: WebSocket):
    """Authenticated live-update stream."""
    user = await _resolve_ws_user(ws)
    if user is None:
        await ws.close(code=4401)
        return

    await ws.accept()
    await connections.add(ws)
    try:
        while True:
            # keep the socket open; we can optionally receive pings
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connections.remove(ws)
