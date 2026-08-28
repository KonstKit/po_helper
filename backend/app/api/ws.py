from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import _resolve_current_user
from app.core.database import AsyncSessionLocal
from app.core.notifications import connections


router = APIRouter()


@router.websocket("/ws")
async def websocket_updates(ws: WebSocket):
    """Authenticated live-update stream.

    Browsers cannot send an Authorization header during a WebSocket
    handshake, so the JWT is accepted via the ``token`` query parameter.
    """
    token = ws.query_params.get("token")
    header = ws.headers.get("authorization")
    if not token and header and header.lower().startswith("bearer "):
        token = header.split(" ", 1)[1]

    if not token:
        await ws.close(code=4401)
        return

    async with AsyncSessionLocal() as db:
        try:
            await _resolve_current_user(
                db, authorization=f"Bearer {token}", allow_debug_demo_fallback=False
            )
        except Exception:
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
