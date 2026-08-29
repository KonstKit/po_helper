"""Shared retry-with-backoff helper for synchronous integration HTTP calls.

One implementation of the retry loop that previously existed as four
near-identical copies (confluence/git-import/testrail/jira clients) -
identical semantics: retry on transport errors and 5xx responses with
exponential backoff, never retry other statuses.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


def request_with_retry(
    do_request: Callable[[], requests.Response],
    *,
    url: str,
    label: str,
    max_retries: Optional[int] = None,
    backoff_base: Optional[float] = None,
    backoff_max: Optional[float] = None,
) -> requests.Response:
    """Run `do_request` with retry/backoff on 5xx and transport errors.

    `do_request` performs the actual HTTP call (method/session/auth are the
    caller's concern); this wrapper owns only the retry policy, keeping the
    per-service copies in sync by construction.
    """
    attempts = (
        settings.INTEGRATION_HTTP_MAX_RETRIES if max_retries is None else max(0, max_retries)
    ) + 1
    base = settings.INTEGRATION_HTTP_BACKOFF_SECONDS if backoff_base is None else backoff_base
    cap = settings.INTEGRATION_HTTP_BACKOFF_MAX_SECONDS if backoff_max is None else backoff_max

    last_exc: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = do_request()
            if resp.status_code >= 500 and attempt < attempts - 1:
                delay = min(base * (2**attempt), cap)
                logger.warning(
                    "%s request failed (%s) retry %d/%d in %.1fs: %s",
                    label,
                    resp.status_code,
                    attempt + 1,
                    attempts - 1,
                    delay,
                    url,
                )
                time.sleep(delay)
                continue
            return resp
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt >= attempts - 1:
                raise
            delay = min(base * (2**attempt), cap)
            logger.warning(
                "%s request error (%s) retry %d/%d in %.1fs: %s",
                label,
                exc.__class__.__name__,
                attempt + 1,
                attempts - 1,
                delay,
                url,
            )
            time.sleep(delay)

    if last_exc:
        raise last_exc
    raise RuntimeError("Unexpected request retry loop exit")


def retry_kwargs(timeout: Optional[int] = None) -> Dict[str, Any]:
    """Standard timeout value for integration HTTP calls."""
    return {"timeout": settings.INTEGRATION_HTTP_TIMEOUT if timeout is None else int(timeout)}
