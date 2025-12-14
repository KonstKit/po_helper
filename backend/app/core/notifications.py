from __future__ import annotations

import asyncio
from typing import Set, Dict, Any
from starlette.websockets import WebSocket


class Connections:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._conns: Set[WebSocket] = set()

    async def add(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.add(ws)

    async def remove(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.discard(ws)

    async def broadcast_json(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            conns = list(self._conns)
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                # Drop broken connection
                try:
                    await self.remove(ws)
                except Exception:
                    pass


connections = Connections()

