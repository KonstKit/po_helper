from __future__ import annotations

from typing import Any, Dict, List

import httpx
import pytest

from app.services.jira.board_service import JiraBoardService


class _DummyHttpClient:
    base_url = "https://jira.example.com"
    email = "jira@example.com"
    api_token = "token"

    def headers(self) -> Dict[str, str]:
        return {"Accept": "application/json"}


class _DummyCircuitBreaker:
    def __init__(self):
        self.success_calls = 0
        self.failure_calls = 0
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def record_success(self) -> None:
        self.success_calls += 1

    def record_failure(self) -> None:
        self.failure_calls += 1


class _DummyVersionResolver:
    def __init__(self, versions: List[str]):
        self.versions = versions

    def get_api_versions(self, _kind: str) -> List[str]:
        return list(self.versions)


class _FakeResponse:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://jira.example.com/fail")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("http error", request=request, response=response)

    def json(self) -> Dict[str, Any]:
        return dict(self._payload)


class _FakeAsyncClient:
    def __init__(self, actions: List[Any]):
        self.actions = actions
        self.calls: List[Dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        action = self.actions[len(self.calls) - 1]
        if isinstance(action, Exception):
            raise action
        return _FakeResponse(payload=action)


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, actions: List[Any]) -> _FakeAsyncClient:
    fake_client = _FakeAsyncClient(actions)

    class _PatchedAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any):
            pass

        async def __aenter__(self) -> _FakeAsyncClient:
            return fake_client

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr("app.services.jira.board_service.httpx.AsyncClient", _PatchedAsyncClient)
    return fake_client


@pytest.fixture(autouse=True)
def _stub_metrics(monkeypatch: pytest.MonkeyPatch):
    class _DummyMetrics:
        def inc(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr("app.services.jira.board_service.metrics", _DummyMetrics())


@pytest.mark.asyncio
async def test_async_get_issue_worklogs_stops_by_total_and_max_results(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.jira.board_service.settings.JIRA_WORKLOG_MAX_PAGES", 50)

    fake_client = _patch_async_client(
        monkeypatch,
        actions=[
            {"startAt": 0, "maxResults": 2, "total": 3, "worklogs": [{"id": "1"}, {"id": "2"}]},
            {"startAt": 2, "maxResults": 2, "total": 3, "worklogs": [{"id": "3"}]},
        ],
    )

    circuit_breaker = _DummyCircuitBreaker()
    service = JiraBoardService(
        http_client=_DummyHttpClient(),
        circuit_breaker=circuit_breaker,
        version_resolver=_DummyVersionResolver(["3"]),
    )

    worklogs = await service.async_get_issue_worklogs("PRJ-1")

    assert [item["id"] for item in worklogs] == ["1", "2", "3"]
    assert len(fake_client.calls) == 2
    assert circuit_breaker.success_calls == 1
    assert circuit_breaker.failure_calls == 0


@pytest.mark.asyncio
async def test_async_get_issue_worklogs_stops_when_page_limit_reached(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.jira.board_service.settings.JIRA_WORKLOG_MAX_PAGES", 2)

    fake_client = _patch_async_client(
        monkeypatch,
        actions=[
            {"startAt": 0, "maxResults": 2, "total": 10, "worklogs": [{"id": "1"}, {"id": "2"}]},
            {"startAt": 2, "maxResults": 2, "total": 10, "worklogs": [{"id": "3"}, {"id": "4"}]},
            {"startAt": 4, "maxResults": 2, "total": 10, "worklogs": [{"id": "5"}, {"id": "6"}]},
        ],
    )

    circuit_breaker = _DummyCircuitBreaker()
    service = JiraBoardService(
        http_client=_DummyHttpClient(),
        circuit_breaker=circuit_breaker,
        version_resolver=_DummyVersionResolver(["3"]),
    )

    worklogs = await service.async_get_issue_worklogs("PRJ-2")

    assert [item["id"] for item in worklogs] == ["1", "2", "3", "4"]
    assert len(fake_client.calls) == 2
    assert circuit_breaker.success_calls == 1
    assert circuit_breaker.failure_calls == 0


@pytest.mark.asyncio
async def test_async_get_issue_worklogs_timeout_is_fail_fast(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.services.jira.board_service.settings.JIRA_WORKLOG_MAX_PAGES", 50)

    fake_client = _patch_async_client(
        monkeypatch,
        actions=[httpx.ReadTimeout("timed out")],
    )

    circuit_breaker = _DummyCircuitBreaker()
    service = JiraBoardService(
        http_client=_DummyHttpClient(),
        circuit_breaker=circuit_breaker,
        version_resolver=_DummyVersionResolver(["3", "2"]),
    )

    worklogs = await service.async_get_issue_worklogs("PRJ-3")

    assert worklogs == []
    # Fail-fast: should not continue to the next API version after timeout.
    assert len(fake_client.calls) == 1
    assert circuit_breaker.success_calls == 0
    assert circuit_breaker.failure_calls == 1
