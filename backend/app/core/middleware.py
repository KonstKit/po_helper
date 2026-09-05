from __future__ import annotations

import asyncio
import re
import uuid
from time import perf_counter
from fastapi import FastAPI, Response
from starlette.types import ASGIApp, Receive, Scope, Send
from app.core.metrics import metrics
from app.core.query_metrics import set_query_context
from app.core.request_context import set_request_id, reset_request_id
from urllib.parse import urlsplit
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.routing import get_route_path
from slowapi.middleware import SlowAPIMiddleware
from app.core.rate_limit import limiter, RateLimitExceeded, _rate_limit_exceeded_handler
from app.core.config import settings


_UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _normalize_http_path(path: str) -> str:
    if not path:
        return "unknown"

    parts = path.split("/")
    normalized_parts: list[str] = []
    for part in parts:
        if not part:
            normalized_parts.append(part)
            continue
        if part.isdigit():
            normalized_parts.append("{id}")
        elif _UUID_PATTERN.fullmatch(part):
            normalized_parts.append("{uuid}")
        elif len(part) > 24 and all(ch.isalnum() or ch in "-_" for ch in part):
            normalized_parts.append("{token}")
        else:
            normalized_parts.append(part)
    normalized = "/".join(normalized_parts)
    return normalized or "/"


def _route_template_path(scope: Scope) -> str | None:
    route = scope.get("route")
    if route is None:
        return None

    path_format = getattr(route, "path_format", None)
    if isinstance(path_format, str) and path_format:
        return path_format

    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path

    return None


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

        request_path = _normalize_http_path(scope.get("path") or "")
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


class ObservabilityMiddleware:
    """Record request volume, latency, and errors with normalized labels."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        fallback_path = _normalize_http_path(scope.get("path") or "")
        method = (scope.get("method") or "UNKNOWN").upper()
        started_at = perf_counter()
        status_code: int | None = None

        async def _send(message):
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status") or 200)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except asyncio.CancelledError:
            status_code = status_code or 499
            raise
        except Exception:
            status_code = status_code or 500
            raise
        finally:
            status_code = status_code or 200
            duration = perf_counter() - started_at
            request_path = _route_template_path(scope) or fallback_path
            labels = {"path": request_path, "method": method, "status": str(status_code)}
            try:
                metrics.inc("http_requests", labels=labels)
                metrics.observe("http_request_latency_seconds", duration, labels=labels)
                if 400 <= status_code < 500:
                    metrics.inc("http_request_client_errors", labels=labels)
                if status_code >= 500:
                    metrics.inc("http_request_errors", labels=labels)
            except Exception:
                pass


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
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(CancelMetricsMiddleware)
    # RequestIdMiddleware should run first to populate context for logs/audit entries
    app.add_middleware(RequestIdMiddleware)
    # QueryContextMiddleware should run early to set context for all queries
    app.add_middleware(QueryContextMiddleware)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(CookieCsrfOriginMiddleware)


class CookieCsrfOriginMiddleware:
    """CSRF defense for cookie-authenticated mutating requests (JWT M2).

    SameSite=strict is the primary mitigation, but samesite is a
    configurable setting, so enforce it in depth: when a mutating
    request carries the auth cookie, an Origin/Referer must be present
    and same-host or listed in CORS_ORIGINS. Cookie-less requests are
    untouched (API clients use bearer tokens)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    SAFE_METHODS = (
        "GET",
        "HEAD",
        "OPTIONS",
    )

    def _reject(self) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Cross-site request rejected",
            },
        )

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] in self.SAFE_METHODS
            or not settings.AUTH_COOKIE_ENABLED
        ):
            await self.app(scope, receive, send)
            return
        # Login CSRF (JWT storage M1): a cross-site form POST to the login
        # endpoints can silently sign the victim into an attacker's account
        # (SameSite permits cookie creation on top-level navigation), so
        # these paths are origin-validated even without cookies.
        path = get_route_path(scope)
        is_login_csrf_path = path in (
            settings.API_V1_STR + "/auth/login",
            settings.API_V1_STR + "/auth/mfa/verify-login",
        )
        headers = Headers(scope=scope)
        if not headers.get("cookie") and not is_login_csrf_path:
            await self.app(scope, receive, send)
            return
        origin_header = headers.get("origin")
        referer = headers.get("referer")
        origin = origin_header
        if not origin and referer:
            parts = urlsplit(referer)
            origin = parts.scheme + "://" + parts.netloc
        allowed = {a.rstrip("/") for a in settings.CORS_ORIGINS}
        host = headers.get("host")
        if host:
            allowed.add("http://" + host)
            allowed.add("https://" + host)
        # A present-but-different origin is always cross-site: reject.
        if origin and origin.rstrip("/") not in allowed:
            response = self._reject()
            await response(scope, receive, send)
            return
        # No Origin/Referer: a non-browser API client driving the cookie
        # manually. SameSite=strict (the default) already blocks cross-site
        # browser sends, so the request is allowed; a weakened SameSite
        # policy must fall back to this header check, and it fails closed.
        # Login endpoints are exempt here: a cookie-less login has no CSRF
        # vector beyond the hostile-origin check above, and breaking
        # non-browser clients would be worse.
        if (
            not origin
            and settings.AUTH_COOKIE_SAMESITE.lower() != "strict"
            and not is_login_csrf_path
        ):
            response = self._reject()
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
