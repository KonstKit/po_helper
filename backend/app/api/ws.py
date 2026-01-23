from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.notifications import connections


router = APIRouter()


@router.websocket("/ws")
async def websocket_updates(ws: WebSocket):
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
