"""HTTP client for Jira API communication with timeout and retry logic."""

import logging
import time
from typing import Dict, Optional

import requests
from requests.auth import HTTPBasicAuth

from app.core.config import settings

logger = logging.getLogger(__name__)


class JiraHttpClient:
    """
    HTTP client for Jira API with configurable timeout and backoff retries.

    Handles:
    - HTTP requests with timeout configuration
    - Automatic retries on timeouts
    - Exponential backoff
    - Bearer token authentication
    - Basic authentication
    """

    def __init__(
        self,
        base_url: str,
        auth: Optional[HTTPBasicAuth] = None,
        bearer_token: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
    ):
        """
        Initialize HTTP client.

        Args:
            base_url: Jira base URL (e.g., 'https://company.atlassian.net')
            auth: HTTPBasicAuth for email + token (Jira Cloud)
            bearer_token: Bearer token for PAT authentication (Jira Server/DC)
            email: Jira user email (used to build Basic auth if auth not provided)
            api_token: Jira API token (used to build Basic auth if auth not provided)
        """
        self.base_url = base_url.rstrip("/") if base_url else None
        self.email = email or getattr(auth, "username", None)
        self.api_token = api_token or getattr(auth, "password", None)

        # Prefer explicit auth, otherwise build from email+token
        self.auth = auth or (
            HTTPBasicAuth(self.email, self.api_token) if self.email and self.api_token else None
        )
        self.bearer_token = bearer_token

        self.timeout = settings.JIRA_HTTP_TIMEOUT or 60
        self.max_retries = getattr(settings, "JIRA_HTTP_MAX_RETRIES", 0) or 0
        self.base_backoff = getattr(settings, "JIRA_HTTP_BACKOFF_SECONDS", 1.0) or 1.0

    def request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """
        Perform HTTP request with configured timeout and retries.

        Retries on ReadTimeout and ConnectTimeout with exponential backoff.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., '/rest/api/3/myself')
            **kwargs: Additional arguments passed to requests.request()

        Returns:
            requests.Response

        Raises:
            requests.exceptions.Timeout: After all retries exhausted
            requests.exceptions.RequestException: On other HTTP errors
        """
        url = endpoint
        if self.base_url and not endpoint.startswith(("http://", "https://")):
            url = f"{self.base_url}{endpoint}"
        timeout = kwargs.pop("timeout", self.timeout)
        max_tries = max(1, self.max_retries + 1)

        last_exc: Optional[Exception] = None

        for attempt in range(max_tries):
            try:
                # Prepare headers
                headers = kwargs.setdefault("headers", {}) or {}
                if "Accept" not in headers:
                    headers["Accept"] = "application/json"

                # Apply authentication
                if self.bearer_token:
                    # Bearer token authentication (PAT)
                    if "Authorization" not in headers:
                        headers["Authorization"] = f"Bearer {self.bearer_token}"
                    # Suppress requests' auth parameter when using Bearer
                    if "auth" not in kwargs or kwargs.get("auth") is None:
                        kwargs["auth"] = None
                elif self.auth:
                    # Basic authentication
                    kwargs.setdefault("auth", self.auth)

                return requests.request(method, url, timeout=timeout, **kwargs)

            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
                last_exc = e
                if attempt < max_tries - 1:
                    delay = self.base_backoff * (2**attempt)
                    logger.warning(
                        "Jira HTTP timeout (%s). Retry %d/%d in %.1fs: %s",
                        e.__class__.__name__,
                        attempt + 1,
                        max_tries - 1,
                        delay,
                        url,
                    )
                    time.sleep(delay)
                    continue
                raise

        # Should never reach here, but for type safety
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected request loop exit")

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        """
        Perform GET request.

        Args:
            endpoint: API endpoint
            **kwargs: Additional arguments

        Returns:
            requests.Response
        """
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> requests.Response:
        """
        Perform POST request.

        Args:
            endpoint: API endpoint
            **kwargs: Additional arguments

        Returns:
            requests.Response
        """
        return self.request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> requests.Response:
        """
        Perform PUT request.

        Args:
            endpoint: API endpoint
            **kwargs: Additional arguments

        Returns:
            requests.Response
        """
        return self.request("PUT", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> requests.Response:
        """
        Perform DELETE request.

        Args:
            endpoint: API endpoint
            **kwargs: Additional arguments

        Returns:
            requests.Response
        """
        return self.request("DELETE", endpoint, **kwargs)

    def headers(self) -> Dict[str, str]:
        """
        Get default headers for Jira requests.

        Returns:
            Dict of headers
        """
        h = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        if self.bearer_token:
            h["Authorization"] = f"Bearer {self.bearer_token}"

        return h

    def basic_auth_tuple(self) -> Optional[tuple[str, str]]:
        """
        Return auth tuple for httpx-style clients.

        Returns:
            Tuple(email, api_token) if available, otherwise None.
        """
        if (
            self.auth
            and getattr(self.auth, "username", None)
            and getattr(self.auth, "password", None)
        ):
            return (str(self.auth.username), str(self.auth.password))

        if self.email and self.api_token:
            return (self.email, self.api_token)

        return None
