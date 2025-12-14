from __future__ import annotations

import asyncio
from fastapi import FastAPI, Request, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.metrics import metrics
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter, RateLimitExceeded, _rate_limit_exceeded_handler


class CancelMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_path = scope.get("path") or ""
        method = scope.get("method") or ""

        headers_sent = False

        async def _send(message):
            nonlocal headers_sent
            if message.get("type") == "http.response.start":
                headers_sent = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except asyncio.CancelledError:
            try:
                metrics.inc("http_request_cancelled_total", labels={"path": request_path, "method": method})
            finally:
                # Only send a 499 if nothing has been started yet to avoid double-send errors
                if not headers_sent:
                    res = Response(content=b"Client Closed Request", status_code=499, media_type="text/plain")
                    await res(scope, receive, send)
        except Exception:
            # Non-cancel exceptions are handled upstream
            raise


def register_middlewares(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(CancelMetricsMiddleware)

