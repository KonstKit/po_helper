import os
import json

import pytest
from requests import Response
from requests.structures import CaseInsensitiveDict

os.environ["SKIP_SERVICE_AUTOCONNECT"] = "1"

from app.services.jira_service import JiraAuthError, JiraService, JiraUnexpectedResponse


def _make_response(
    status: int = 200,
    *,
    data=None,
    text: str = "{}",
    ctype: str = "application/json",
    url: str = "https://example.atlassian.net/api",
) -> Response:
    resp = Response()
    resp.status_code = status
    resp.url = url
    payload = json.dumps(data).encode("utf-8") if data is not None else text.encode("utf-8")
    resp._content = payload
    resp.headers = CaseInsensitiveDict({"Content-Type": ctype})
    return resp


@pytest.fixture(autouse=True)
def stub_metrics(monkeypatch):
    class _DummyMetrics:
        def inc(self, *args, **kwargs):
            return None

        def set_gauge(self, *args, **kwargs):
            return None

    dummy = _DummyMetrics()
    monkeypatch.setattr("app.services.jira_service.metrics", dummy)
    return dummy


@pytest.fixture()
def service():
    return JiraService()


def test_handle_response_success_returns_json(service):
    response = _make_response(data={"key": "value"})
    payload = service._handle_response("project_search_v3", response)
    assert payload == {"key": "value"}


def test_handle_response_raises_for_non_json_response(service):
    response = _make_response(ctype="text/html", text="<html>login</html>")
    with pytest.raises(JiraUnexpectedResponse):
        service._handle_response("project_search_v3", response)


def test_handle_response_raises_for_auth_error(service):
    response = _make_response(status=401)
    with pytest.raises(JiraAuthError):
        service._handle_response("project_search_v3", response)
