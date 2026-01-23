"""Response handler for Jira API with validation and error detection."""

import logging
from typing import Any

import requests

from app.core.metrics import metrics

logger = logging.getLogger(__name__)


class JiraAuthError(Exception):
    """Raised when Jira returns an authentication or authorization failure."""

    pass


class JiraUnexpectedResponse(Exception):
    """Raised when Jira returns a non-JSON or otherwise unexpected payload."""

    pass


class JiraResponseHandler:
    """
    Validates and parses Jira API responses.

    Handles:
    - Authentication error detection
    - Non-JSON response detection
    - JSON parsing and validation
    - Metrics reporting
    - Detailed error logging
    """

    def handle_response(self, endpoint: str, response: requests.Response) -> Any:
        """
        Validate a Jira response ensuring we get JSON payloads.

        When Jira returns HTML (e.g. login redirect) or other unexpected payloads,
        raises explicit exceptions so callers can react appropriately.

        Args:
            endpoint: API endpoint being called (for logging)
            response: HTTP response from Jira

        Returns:
            Parsed JSON data from response

        Raises:
            JiraAuthError: When authentication is required
            JiraUnexpectedResponse: When response is not valid JSON
            requests.HTTPError: On HTTP error status codes
        """
        # Check for authentication errors
        if self._is_auth_error(response):
            body = (getattr(response, "text", "") or "")[:200]
            logger.warning("Jira auth required for %s: %s", endpoint, body)
            raise JiraAuthError(f"Jira authentication required for endpoint '{endpoint}'")

        # Raise for HTTP errors (4xx, 5xx)
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise

        # Validate content type
        ctype = (response.headers.get("content-type") or "").lower()
        if "application/json" not in ctype:
            self._record_non_json_metric(endpoint)
            body = (response.text or "")[:500]
            logger.error("Non-JSON response from Jira (%s): %s", endpoint, ctype)
            logger.debug("Response body sample (%s): %s", endpoint, body)
            raise JiraUnexpectedResponse(f"Expected JSON, got {ctype}")

        # Parse JSON
        try:
            return response.json()
        except ValueError as exc:
            self._record_json_parse_error(endpoint)
            body = (response.text or "")[:500]
            logger.error("Failed to decode Jira JSON (%s): %s", endpoint, exc)
            logger.debug("Response body sample (%s): %s", endpoint, body)
            raise JiraUnexpectedResponse(f"Invalid JSON payload from Jira ({endpoint})") from exc

    def _is_auth_error(self, response: requests.Response) -> bool:
        """
        Detect if response indicates authentication error.

        Checks for:
        - 401, 403, 407 status codes
        - Redirects to login pages
        - HTML responses with login markers

        Args:
            response: HTTP response

        Returns:
            True if authentication is required
        """
        status = response.status_code

        # Direct auth errors
        if status in (401, 403, 407):
            return True

        # Redirects to login endpoints imply auth failure
        if status in (301, 302, 303, 307, 308):
            location = (response.headers.get("location") or "").lower()
            if any(
                term in location for term in ("login", "logon", "auth", "signin", "session-expired")
            ):
                return True

        # HTML responses with login markers
        ctype = (response.headers.get("content-type") or "").lower()
        if "text/html" in ctype and status >= 400:
            try:
                snippet = (response.text or "").lower()[:1024]
            except Exception:
                snippet = ""

            login_markers = (
                "login",
                "log in",
                "atlassian-account",
                "atlassian login",
                "sso",
                "session expired",
                "sign in",
                "authenticate",
            )

            if any(marker in snippet for marker in login_markers):
                return True

        return False

    def _record_non_json_metric(self, endpoint: str) -> None:
        """Record metric for non-JSON response."""
        try:
            metrics.inc("jira_non_json_total", labels={"ep": endpoint})
        except Exception as e:
            logger.debug("Failed to record non-JSON metric: %s", e)

    def _record_json_parse_error(self, endpoint: str) -> None:
        """Record metric for JSON parse error."""
        try:
            metrics.inc("jira_json_parse_error_total", labels={"ep": endpoint})
        except Exception as e:
            logger.debug("Failed to record JSON parse error metric: %s", e)

    def validate_json_response(self, response: requests.Response) -> bool:
        """
        Check if response is valid JSON without parsing.

        Args:
            response: HTTP response

        Returns:
            True if response appears to be valid JSON
        """
        ctype = (response.headers.get("content-type") or "").lower()
        return "application/json" in ctype and response.status_code == 200
