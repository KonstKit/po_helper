"""
Bitbucket Cloud and Bitbucket Server (Data Center) API client.

Supports:
- Bitbucket Cloud (bitbucket.org) with App Passwords or OAuth
- Bitbucket Server/Data Center with Personal Access Tokens (PAT)

Provides async methods for:
- Pull request listing and details
- Repository information
- Commit history
- Branch management
"""

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

import httpx

LOGGER = logging.getLogger(__name__)


class BitbucketType(Enum):
    """Type of Bitbucket instance."""

    CLOUD = "cloud"
    SERVER = "server"


class BitbucketAPIError(Exception):
    """Raised when Bitbucket API returns an unexpected response."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class BitbucketAuth:
    """Authentication configuration for Bitbucket."""

    instance_type: BitbucketType
    base_url: str
    # For Cloud: username + app_password (Basic Auth)
    # For Server: just token (Bearer Auth)
    username: Optional[str] = None
    app_password: Optional[str] = None
    access_token: Optional[str] = None


BITBUCKET_CLOUD_API = "https://api.bitbucket.org/2.0"


def detect_instance_type(base_url: str) -> BitbucketType:
    """Detect if URL is Bitbucket Cloud or Server/Data Center."""
    normalized = base_url.lower().strip().rstrip("/")
    if "bitbucket.org" in normalized or "api.bitbucket.org" in normalized:
        return BitbucketType.CLOUD
    return BitbucketType.SERVER


def get_api_base(base_url: str, instance_type: BitbucketType) -> str:
    """Get the API base URL for the instance type."""
    base = base_url.strip().rstrip("/")

    if instance_type == BitbucketType.CLOUD:
        # Always use the cloud API endpoint
        return BITBUCKET_CLOUD_API
    else:
        # For Server/Data Center, append /rest/api/latest if not already present
        if "/rest/api/" not in base.lower():
            return f"{base}/rest/api/latest"
        return base


def build_headers(auth: BitbucketAuth) -> Dict[str, str]:
    """Build HTTP headers for Bitbucket API requests."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "po-helper",
    }

    if auth.instance_type == BitbucketType.CLOUD:
        # Cloud uses Basic Auth with username:app_password
        if auth.username and auth.app_password:
            import base64

            credentials = base64.b64encode(f"{auth.username}:{auth.app_password}".encode()).decode(
                "ascii"
            )
            headers["Authorization"] = f"Basic {credentials}"
        elif auth.access_token:
            # OAuth2 bearer token
            headers["Authorization"] = f"Bearer {auth.access_token}"
    else:
        # Server/Data Center uses Bearer token (PAT)
        if auth.access_token:
            headers["Authorization"] = f"Bearer {auth.access_token}"

    return headers


async def test_connection(
    base_url: str,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    access_token: Optional[str] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """
    Test Bitbucket connection and return user/instance info.

    Args:
        base_url: Bitbucket instance URL
        username: Username for Cloud App Password auth
        app_password: App Password for Cloud
        access_token: PAT for Server or OAuth token for Cloud
        timeout: Request timeout in seconds

    Returns:
        Connection status and user information
    """
    instance_type = detect_instance_type(base_url)
    api_base = get_api_base(base_url, instance_type)

    auth = BitbucketAuth(
        instance_type=instance_type,
        base_url=base_url,
        username=username,
        app_password=app_password,
        access_token=access_token,
    )

    headers = build_headers(auth)

    # Check if we have any authentication
    if "Authorization" not in headers:
        raise BitbucketAPIError("No authentication credentials provided")

    async with httpx.AsyncClient(timeout=timeout) as client:
        if instance_type == BitbucketType.CLOUD:
            # Cloud: GET /user
            url = f"{api_base}/user"
        else:
            # Server: GET /users/{username} or /application-properties for anon check
            # First try to get current user via /users endpoint
            url = f"{api_base}/users"

        try:
            response = await client.get(url, headers=headers)
        except httpx.TimeoutException:
            raise BitbucketAPIError("Request timed out", status_code=504)
        except httpx.RequestError as exc:
            raise BitbucketAPIError(f"Request failed: {exc}")

        if response.status_code == 401:
            raise BitbucketAPIError("Authentication failed", status_code=401)
        if response.status_code == 403:
            raise BitbucketAPIError("Access forbidden", status_code=403)
        if response.status_code >= 400:
            msg = _extract_error_message(response)
            raise BitbucketAPIError(f"API error: {msg}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError:
            data = {}

        result: Dict[str, Any] = {
            "status": "connected",
            "instance_type": instance_type.value,
            "base_url": base_url,
            "api_base": api_base,
        }

        if instance_type == BitbucketType.CLOUD:
            result.update(
                {
                    "username": data.get("username"),
                    "display_name": data.get("display_name"),
                    "account_id": data.get("account_id"),
                }
            )
        else:
            # Server response structure is different
            if isinstance(data, dict) and "values" in data:
                # List of users response
                result["user_count"] = len(data.get("values", []))
            else:
                result["data"] = data

        return result


async def fetch_pull_requests(
    base_url: str,
    workspace: str,
    repo_slug: str,
    *,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    access_token: Optional[str] = None,
    state: str = "OPEN",
    per_page: int = 25,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """
    Fetch pull requests from a Bitbucket repository.

    Args:
        base_url: Bitbucket instance URL
        workspace: Workspace/project key (Cloud) or project key (Server)
        repo_slug: Repository slug
        username: Username for Cloud auth
        app_password: App Password for Cloud
        access_token: PAT for Server or OAuth token
        state: PR state filter (OPEN, MERGED, DECLINED, SUPERSEDED)
        per_page: Number of PRs to fetch (max 50 for Cloud, 100 for Server)
        timeout: Request timeout

    Returns:
        List of pull request dictionaries
    """
    instance_type = detect_instance_type(base_url)
    api_base = get_api_base(base_url, instance_type)

    auth = BitbucketAuth(
        instance_type=instance_type,
        base_url=base_url,
        username=username,
        app_password=app_password,
        access_token=access_token,
    )

    headers = build_headers(auth)

    if "Authorization" not in headers:
        raise BitbucketAPIError("No authentication credentials provided")

    async with httpx.AsyncClient(timeout=timeout) as client:
        params: Dict[str, str | int | float | bool | None]
        if instance_type == BitbucketType.CLOUD:
            # Cloud: GET /repositories/{workspace}/{repo_slug}/pullrequests
            url = f"{api_base}/repositories/{workspace}/{repo_slug}/pullrequests"
            params = {
                "state": state.upper(),
                "pagelen": min(per_page, 50),
            }
        else:
            # Server: GET /projects/{projectKey}/repos/{repoSlug}/pull-requests
            url = f"{api_base}/projects/{workspace}/repos/{repo_slug}/pull-requests"
            params = {
                "state": state.upper(),
                "limit": min(per_page, 100),
            }

        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException:
            raise BitbucketAPIError("Request timed out", status_code=504)
        except httpx.RequestError as exc:
            raise BitbucketAPIError(f"Request failed: {exc}")

        if response.status_code == 401:
            raise BitbucketAPIError("Authentication failed", status_code=401)
        if response.status_code == 404:
            raise BitbucketAPIError(
                f"Repository not found: {workspace}/{repo_slug}", status_code=404
            )
        if response.status_code >= 400:
            msg = _extract_error_message(response)
            raise BitbucketAPIError(f"API error: {msg}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError:
            raise BitbucketAPIError("Invalid JSON response")

        # Normalize response format
        if instance_type == BitbucketType.CLOUD:
            return data.get("values", [])
        else:
            # Server response has same structure
            return data.get("values", [])


async def fetch_commits(
    base_url: str,
    workspace: str,
    repo_slug: str,
    *,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    access_token: Optional[str] = None,
    branch: Optional[str] = None,
    per_page: int = 25,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """
    Fetch commits from a Bitbucket repository.

    Args:
        base_url: Bitbucket instance URL
        workspace: Workspace/project key
        repo_slug: Repository slug
        branch: Optional branch filter
        per_page: Number of commits to fetch
        timeout: Request timeout

    Returns:
        List of commit dictionaries
    """
    instance_type = detect_instance_type(base_url)
    api_base = get_api_base(base_url, instance_type)

    auth = BitbucketAuth(
        instance_type=instance_type,
        base_url=base_url,
        username=username,
        app_password=app_password,
        access_token=access_token,
    )

    headers = build_headers(auth)

    if "Authorization" not in headers:
        raise BitbucketAPIError("No authentication credentials provided")

    async with httpx.AsyncClient(timeout=timeout) as client:
        params: Dict[str, str | int | float | bool | None]
        if instance_type == BitbucketType.CLOUD:
            url = f"{api_base}/repositories/{workspace}/{repo_slug}/commits"
            params = {"pagelen": min(per_page, 50)}
            if branch:
                params["include"] = branch
        else:
            url = f"{api_base}/projects/{workspace}/repos/{repo_slug}/commits"
            params = {"limit": min(per_page, 100)}
            if branch:
                params["until"] = f"refs/heads/{branch}"

        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException:
            raise BitbucketAPIError("Request timed out", status_code=504)
        except httpx.RequestError as exc:
            raise BitbucketAPIError(f"Request failed: {exc}")

        if response.status_code >= 400:
            msg = _extract_error_message(response)
            raise BitbucketAPIError(f"API error: {msg}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError:
            raise BitbucketAPIError("Invalid JSON response")

        return data.get("values", [])


async def fetch_branches(
    base_url: str,
    workspace: str,
    repo_slug: str,
    *,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    access_token: Optional[str] = None,
    per_page: int = 25,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """
    Fetch branches from a Bitbucket repository.

    Returns:
        List of branch dictionaries
    """
    instance_type = detect_instance_type(base_url)
    api_base = get_api_base(base_url, instance_type)

    auth = BitbucketAuth(
        instance_type=instance_type,
        base_url=base_url,
        username=username,
        app_password=app_password,
        access_token=access_token,
    )

    headers = build_headers(auth)

    if "Authorization" not in headers:
        raise BitbucketAPIError("No authentication credentials provided")

    async with httpx.AsyncClient(timeout=timeout) as client:
        params: Dict[str, str | int | float | bool | None]
        if instance_type == BitbucketType.CLOUD:
            url = f"{api_base}/repositories/{workspace}/{repo_slug}/refs/branches"
            params = {"pagelen": min(per_page, 100)}
        else:
            url = f"{api_base}/projects/{workspace}/repos/{repo_slug}/branches"
            params = {"limit": min(per_page, 100)}

        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException:
            raise BitbucketAPIError("Request timed out", status_code=504)
        except httpx.RequestError as exc:
            raise BitbucketAPIError(f"Request failed: {exc}")

        if response.status_code >= 400:
            msg = _extract_error_message(response)
            raise BitbucketAPIError(f"API error: {msg}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError:
            raise BitbucketAPIError("Invalid JSON response")

        return data.get("values", [])


async def fetch_repositories(
    base_url: str,
    workspace: str,
    *,
    username: Optional[str] = None,
    app_password: Optional[str] = None,
    access_token: Optional[str] = None,
    per_page: int = 25,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """
    Fetch repositories from a Bitbucket workspace/project.

    Returns:
        List of repository dictionaries
    """
    instance_type = detect_instance_type(base_url)
    api_base = get_api_base(base_url, instance_type)

    auth = BitbucketAuth(
        instance_type=instance_type,
        base_url=base_url,
        username=username,
        app_password=app_password,
        access_token=access_token,
    )

    headers = build_headers(auth)

    if "Authorization" not in headers:
        raise BitbucketAPIError("No authentication credentials provided")

    async with httpx.AsyncClient(timeout=timeout) as client:
        params: Dict[str, str | int | float | bool | None]
        if instance_type == BitbucketType.CLOUD:
            url = f"{api_base}/repositories/{workspace}"
            params = {"pagelen": min(per_page, 100)}
        else:
            url = f"{api_base}/projects/{workspace}/repos"
            params = {"limit": min(per_page, 100)}

        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.TimeoutException:
            raise BitbucketAPIError("Request timed out", status_code=504)
        except httpx.RequestError as exc:
            raise BitbucketAPIError(f"Request failed: {exc}")

        if response.status_code >= 400:
            msg = _extract_error_message(response)
            raise BitbucketAPIError(f"API error: {msg}", status_code=response.status_code)

        try:
            data = response.json()
        except ValueError:
            raise BitbucketAPIError("Invalid JSON response")

        return data.get("values", [])


def _extract_error_message(response: httpx.Response) -> str:
    """Extract error message from Bitbucket API response."""
    try:
        data = response.json()
        if isinstance(data, dict):
            # Cloud format
            if "error" in data:
                error = data["error"]
                if isinstance(error, dict):
                    return error.get("message", str(error))
                return str(error)
            # Server format
            if "errors" in data:
                errors = data["errors"]
                if isinstance(errors, list) and errors:
                    return errors[0].get("message", str(errors[0]))
            if "message" in data:
                return data["message"]
    except Exception:
        pass
    return response.text[:200] if response.text else "Unknown error"
