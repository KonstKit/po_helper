from __future__ import annotations

import asyncio
import uuid
from fastapi import FastAPI, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.metrics import metrics
from app.core.query_metrics import set_query_context
from app.core.request_context import set_request_id, reset_request_id
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter, RateLimitExceeded, _rate_limit_exceeded_handler


class QueryContextMiddleware:
    """Middleware to set query context for database metrics.

    This middleware sets the current endpoint path as context for query metrics,
    allowing us to track which endpoints generate which database queries.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Set query context for this request
        request_path = scope.get("path") or "unknown"
        set_query_context(request_path)

        await self.app(scope, receive, send)


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
                metrics.inc(
                    "http_request_cancelled_total", labels={"path": request_path, "method": method}
                )
            finally:
                # Only send a 499 if nothing has been started yet to avoid double-send errors
                if not headers_sent:
                    res = Response(
                        content=b"Client Closed Request", status_code=499, media_type="text/plain"
                    )
                    await res(scope, receive, send)
        except Exception:
            # Non-cancel exceptions are handled upstream
            raise


class RequestIdMiddleware:
    """Assign or propagate a request_id for each HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = None
        for key, value in scope.get("headers") or []:
            if key.lower() == b"x-request-id":
                request_id = value.decode("utf-8", errors="ignore").strip() or None
                break
        if request_id is None:
            request_id = str(uuid.uuid4())

        token = set_request_id(request_id)

        async def _send(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("utf-8")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            reset_request_id(token)


def register_middlewares(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(CancelMetricsMiddleware)
    # RequestIdMiddleware should run first to populate context for logs/audit entries
    app.add_middleware(RequestIdMiddleware)
    # QueryContextMiddleware should run early to set context for all queries
    app.add_middleware(QueryContextMiddleware)
