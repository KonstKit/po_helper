from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import settings

logger = logging.getLogger(__name__)


class TestRailAPIError(RuntimeError):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TestRailClient:
    """Minimal async TestRail client with retries and pagination."""

    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        *,
        timeout_seconds: Optional[int] = None,
        max_retries: Optional[int] = None,
        backoff_base_seconds: Optional[float] = None,
        backoff_max_seconds: Optional[float] = None,
        retry_after_header: bool = True,
        page_limit: int = 250,
    ) -> None:
        if not base_url:
            raise ValueError("TestRail base_url is required")
        if not email:
            raise ValueError("TestRail email is required")
        if not api_token:
            raise ValueError("TestRail api_token is required")

        base = base_url.rstrip("/")
        if base.endswith("/index.php"):
            base = base[: -len("/index.php")]

        self.base_url = base
        self.api_base = f"{self.base_url}/index.php?/api/v2"
        self.auth = HTTPBasicAuth(email, api_token)
        self.retry_after_header = retry_after_header
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.INTEGRATION_HTTP_TIMEOUT
        )
        self.max_retries = (
            max_retries if max_retries is not None else settings.INTEGRATION_HTTP_MAX_RETRIES
        )
        self.backoff_base_seconds = (
            backoff_base_seconds
            if backoff_base_seconds is not None
            else settings.INTEGRATION_HTTP_BACKOFF_SECONDS
        )
        self.backoff_max_seconds = (
            backoff_max_seconds
            if backoff_max_seconds is not None
            else settings.INTEGRATION_HTTP_BACKOFF_MAX_SECONDS
        )
        self.page_limit = max(1, page_limit)
        self._session: requests.Session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    async def get_projects(self) -> List[Dict[str, Any]]:
        return await self._get_list("get_projects")

    async def get_suites(self, project_id: int) -> List[Dict[str, Any]]:
        return await self._get_list(f"get_suites/{project_id}")

    async def get_cases(
        self,
        project_id: int,
        *,
        suite_id: Optional[int] = None,
        updated_after: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if suite_id is not None:
            params["suite_id"] = suite_id
        if updated_after is not None:
            params["updated_after"] = updated_after
        return await self._paginate(f"get_cases/{project_id}", params=params, list_key="cases")

    async def get_runs(
        self, project_id: int, *, is_completed: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {}
        if is_completed is not None:
            params["is_completed"] = int(is_completed)
        return await self._paginate(f"get_runs/{project_id}", params=params, list_key="runs")

    async def get_results(self, run_id: int) -> List[Dict[str, Any]]:
        return await self._paginate(
            f"get_results_for_run/{run_id}", params=None, list_key="results"
        )

    async def _get_list(self, endpoint: str) -> List[Dict[str, Any]]:
        payload = await self._request_json("GET", endpoint, params=None)
        return self._extract_list(payload, list_key=None)

    async def _paginate(
        self,
        endpoint: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        list_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        offset = 0
        items: List[Dict[str, Any]] = []
        while True:
            page_params = dict(params or {})
            page_params["limit"] = self.page_limit
            page_params["offset"] = offset
            payload = await self._request_json("GET", endpoint, params=page_params)
            page = self._extract_list(payload, list_key=list_key)
            if not page:
                break
            items.extend(page)
            if len(page) < self.page_limit:
                break
            offset += len(page)
        return items

    async def _request_json(
        self, method: str, endpoint: str, *, params: Optional[Dict[str, Any]]
    ) -> Any:
        return await asyncio.to_thread(self._request_json_sync, method, endpoint, params)

    def _request_json_sync(
        self, method: str, endpoint: str, params: Optional[Dict[str, Any]]
    ) -> Any:
        url = endpoint if endpoint.startswith("http") else f"{self.api_base}/{endpoint.lstrip('/')}"
        attempts = self.max_retries + 1
        last_exc: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                resp = self._session.request(
                    method,
                    url,
                    auth=self.auth,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    delay = self._retry_delay(resp, attempt)
                    logger.warning(
                        "TestRail request failed (%s) retry %d/%d in %.1fs: %s",
                        resp.status_code,
                        attempt + 1,
                        attempts - 1,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    snippet = resp.text[:200] if resp.text else ""
                    raise TestRailAPIError(
                        f"TestRail error {resp.status_code}: {snippet or 'unknown'}",
                        status_code=resp.status_code,
                    )
                try:
                    return resp.json()
                except ValueError as exc:
                    raise TestRailAPIError("TestRail returned non-JSON response") from exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt >= attempts - 1:
                    raise
                delay = min(self.backoff_base_seconds * (2**attempt), self.backoff_max_seconds)
                logger.warning(
                    "TestRail request error (%s) retry %d/%d in %.1fs: %s",
                    exc.__class__.__name__,
                    attempt + 1,
                    attempts - 1,
                    delay,
                    url,
                )
                time.sleep(delay)

        if last_exc:
            raise last_exc
        raise TestRailAPIError("Unexpected TestRail request retry loop exit")

    def _retry_delay(self, response: requests.Response, attempt: int) -> float:
        if self.retry_after_header:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return float(retry_after)
                except ValueError:
                    pass
        return min(self.backoff_base_seconds * (2**attempt), self.backoff_max_seconds)

    def _extract_list(self, payload: Any, list_key: Optional[str]) -> List[Dict[str, Any]]:
        if list_key and isinstance(payload, dict):
            items = payload.get(list_key)
            if isinstance(items, list):
                return items
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("projects", "suites", "cases", "runs", "results"):
                items = payload.get(key)
                if isinstance(items, list):
                    return items
        return []
