import logging
from typing import Any, Dict, List, Optional

import httpx

GITHUB_DEFAULT_API = "https://api.github.com"
LOGGER = logging.getLogger(__name__)


class GitHubAPIError(Exception):
    """Raised when GitHub returns an unexpected response."""


async def fetch_pull_requests(
    token: str,
    repo_slug: str,
    *,
    base_url: Optional[str] = None,
    state: str = "open",
    per_page: int = 30,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    """Fetch pull requests for a given repository via the GitHub REST API.

    Args:
        token: Personal access token or installation token.
        repo_slug: Repository identifier in the form "owner/repo".
        base_url: Optional custom API base URL (for GitHub Enterprise).
        state: PR state filter (e.g. "open", "closed", "all").
        per_page: Number of PRs to fetch (GitHub supports up to 100).
        timeout: Request timeout in seconds.

    Returns:
        A list of pull request dictionaries as returned by GitHub.
    """
    if not token:
        raise GitHubAPIError("GitHub token is required")
    if not repo_slug or "/" not in repo_slug:
        raise GitHubAPIError("Repository slug must be in the form 'owner/repo'")

    per_page = max(1, min(int(per_page), 100))
    api_base = (base_url or GITHUB_DEFAULT_API).rstrip("/")
    url = f"{api_base}/repos/{repo_slug}/pulls"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "po-helper",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    params: Dict[str, str | int | float | bool | None] = {"state": state, "per_page": per_page}

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(url, headers=headers, params=params)

        if response.status_code == 401:
            raise GitHubAPIError("GitHub authentication failed (401)")
        if response.status_code == 404:
            raise GitHubAPIError("Repository not found or access denied")
        if response.status_code >= 400:
            LOGGER.warning("GitHub API returned %s: %s", response.status_code, response.text[:200])
            raise GitHubAPIError(f"GitHub API error {response.status_code}")

        try:
            data = response.json()
        except ValueError as exc:
            raise GitHubAPIError("Invalid JSON response from GitHub") from exc

        if not isinstance(data, list):
            raise GitHubAPIError("Unexpected GitHub API payload")

        return data
