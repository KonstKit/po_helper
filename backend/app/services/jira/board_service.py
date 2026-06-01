"""Jira board and sprint operations service."""

import logging
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.core.metrics import metrics
from app.services.jira.http_client import JiraHttpClient
from app.services.jira.circuit_breaker import CircuitBreaker
from app.services.jira.version_resolver import JiraApiVersionResolver

logger = logging.getLogger(__name__)


class JiraBoardService:
    """
    Handles Jira board and sprint operations.

    Responsibilities:
    - List boards for a project
    - List sprints for a board
    - List issues in a sprint
    - Get issue worklogs (time tracking)
    - Async versions of worklog methods

    All methods use injected dependencies for HTTP, circuit breaker,
    and API version resolution.
    """

    def __init__(
        self,
        http_client: JiraHttpClient,
        circuit_breaker: CircuitBreaker,
        version_resolver: JiraApiVersionResolver,
    ):
        """
        Initialize board service.

        Args:
            http_client: HTTP client for making requests
            circuit_breaker: Circuit breaker for resilience
            version_resolver: API version resolver
        """
        self.http_client = http_client
        self.circuit_breaker = circuit_breaker
        self.version_resolver = version_resolver

    def list_boards_for_project(self, project_key: str) -> List[Dict[str, Any]]:
        """
        List all boards for a Jira project.

        Uses Agile API (always version 1.0) to fetch boards.

        Args:
            project_key: Jira project key

        Returns:
            List of board dicts (id, name, type, etc.)
        """
        if self.circuit_breaker.is_open():
            return []

        endpoint = "/rest/agile/1.0/board"
        params = {"projectKeyOrId": project_key}
        # Boards endpoint is used by interactive UI. Keep it fail-fast to avoid
        # long request hangs when Jira is slow/unreachable.
        boards_timeout = min(int(getattr(settings, "JIRA_HTTP_TIMEOUT", 25) or 25), 10)

        try:
            response = self.http_client.get(
                endpoint,
                params=params,
                timeout=boards_timeout,
                max_retries=0,
            )
            response.raise_for_status()

            # Check content type
            ctype = (response.headers.get("content-type") or "").lower()
            if "application/json" not in ctype:
                try:
                    metrics.inc("jira_non_json_total", labels={"ep": "boards"})
                except Exception:
                    pass
                body = (response.text or "")[:200]
                logger.error("Non-JSON response from Jira boards: %s", ctype)
                raise ValueError(f"Non-JSON response ctype={ctype} body={body}")

            data = response.json()
            items = data.get("values", [])

            self.circuit_breaker.record_success()
            return items

        except Exception as e:
            logger.warning("Jira list_boards failed: %s", e)
            self.circuit_breaker.record_failure()
            return []

    def list_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """
        List all sprints for a Jira board with pagination.

        Fetches all sprints (active, closed, future) with automatic pagination.

        Args:
            board_id: Jira board ID

        Returns:
            List of sprint dicts (id, name, state, startDate, endDate, goal)
        """
        if self.circuit_breaker.is_open():
            logger.warning("Circuit breaker open for Jira, returning empty sprints")
            return []

        endpoint = f"/rest/agile/1.0/board/{board_id}/sprint"
        start_at = 0
        all_items: List[Dict[str, Any]] = []
        max_results = settings.JIRA_MAX_RESULTS
        page_size = settings.JIRA_PAGE_SIZE
        # Sprint lookup is UI-critical and should degrade quickly instead of
        # blocking the page on repeated timeout retries.
        sprint_timeout = min(int(getattr(settings, "JIRA_HTTP_TIMEOUT", 25) or 25), 10)

        try:
            while len(all_items) < max_results:
                current_page_size = min(page_size, max_results - len(all_items))
                params = {
                    "startAt": start_at,
                    "maxResults": current_page_size,
                    "state": "active,closed,future",
                }

                # Use shorter timeout for sprint queries
                response = self.http_client.get(
                    endpoint,
                    params=params,
                    timeout=sprint_timeout,
                    max_retries=0,
                )
                response.raise_for_status()

                # Check content type
                ctype = (response.headers.get("content-type") or "").lower()
                if "application/json" not in ctype:
                    try:
                        metrics.inc("jira_non_json_total", labels={"ep": "sprints"})
                    except Exception:
                        pass
                    body = (response.text or "")[:200]
                    raise ValueError(f"Non-JSON response ctype={ctype} body={body}")

                data = response.json()
                items = data.get("values", [])
                all_items.extend(items)

                # Log progress for large datasets
                total = data.get("total", 0)
                if total > 10:
                    logger.info(
                        f"Fetching sprints for board {board_id}: "
                        f"{start_at + len(items)}/{min(total, max_results)}"
                    )

                if len(items) == 0:
                    break
                start_at += len(items)

            self.circuit_breaker.record_success()
            logger.info(f"Fetched {len(all_items)} sprints for board {board_id}")
            return all_items

        except Exception as e:
            logger.warning("Jira list_sprints failed: %s", e)
            self.circuit_breaker.record_failure()
            return []

    def list_issues_in_sprint(self, sprint_id: int) -> List[Dict[str, Any]]:
        """
        List all issues in a sprint.

        Args:
            sprint_id: Jira sprint ID

        Returns:
            List of issue dicts (key and other fields)
        """
        if self.circuit_breaker.is_open():
            return []

        endpoint = f"/rest/agile/1.0/sprint/{sprint_id}/issue"
        start_at = 0
        all_items: List[Dict[str, Any]] = []
        max_pages = max(
            1,
            int(getattr(settings, "JIRA_SPRINT_ISSUES_MAX_PAGES", 500) or 500),
        )
        seen_starts = set()
        sprint_issues_timeout = min(int(getattr(settings, "JIRA_HTTP_TIMEOUT", 25) or 25), 15)

        try:
            while True:
                if start_at in seen_starts:
                    logger.warning(
                        "Detected sprint issues pagination loop for sprint %s, startAt=%s",
                        sprint_id,
                        start_at,
                    )
                    break
                if len(seen_starts) >= max_pages:
                    logger.warning(
                        "Sprint issues pagination page limit reached for sprint %s: %s pages",
                        sprint_id,
                        max_pages,
                    )
                    break
                seen_starts.add(start_at)

                params = {"startAt": start_at, "maxResults": 50, "fields": "key"}

                response = self.http_client.get(
                    endpoint,
                    params=params,
                    timeout=sprint_issues_timeout,
                    max_retries=0,
                )
                response.raise_for_status()

                # Check content type
                ctype = (response.headers.get("content-type") or "").lower()
                if "application/json" not in ctype:
                    try:
                        metrics.inc("jira_non_json_total", labels={"ep": "sprint_issues"})
                    except Exception:
                        pass
                    body = (response.text or "")[:200]
                    raise ValueError(f"Non-JSON response ctype={ctype} body={body}")

                data = response.json()
                issues = data.get("issues", [])
                all_items.extend(issues)

                if not issues:
                    break

                response_start_at = data.get("startAt") if isinstance(data, dict) else None
                current_start_at = (
                    int(response_start_at) if isinstance(response_start_at, int) else start_at
                )
                response_max_results = data.get("maxResults") if isinstance(data, dict) else None
                current_max_results = (
                    int(response_max_results)
                    if isinstance(response_max_results, int) and response_max_results > 0
                    else params["maxResults"]
                )
                next_start_at = current_start_at + len(issues)
                total_count = data.get("total") if isinstance(data, dict) else None

                if isinstance(total_count, int) and next_start_at >= total_count:
                    break
                if len(issues) < current_max_results:
                    break
                if next_start_at <= current_start_at:
                    logger.warning(
                        "Non-advancing sprint issues pagination for sprint %s, breaking at %s",
                        sprint_id,
                        current_start_at,
                    )
                    break
                start_at = next_start_at

            self.circuit_breaker.record_success()
            return all_items

        except Exception as e:
            logger.warning("Jira list_issues_in_sprint failed: %s", e)
            self.circuit_breaker.record_failure()
            return []

    def get_issue_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Get all worklogs (time tracking) for an issue.

        Tries appropriate API versions and handles pagination.

        Args:
            issue_key: Jira issue key (e.g., "PROJ-123")

        Returns:
            List of worklog dicts (author, timeSpent, started, comment, etc.)
        """
        if self.circuit_breaker.is_open():
            return []

        versions = self.version_resolver.get_api_versions("default")
        last_err: Optional[Exception] = None

        for ver in versions:
            endpoint = f"/rest/api/{ver}/issue/{issue_key}/worklog"
            start_at = 0
            items: List[Dict[str, Any]] = []
            max_pages = max(1, int(getattr(settings, "JIRA_WORKLOG_MAX_PAGES", 2000) or 2000))
            seen_starts = set()

            try:
                while True:
                    if start_at in seen_starts:
                        logger.warning(
                            "Detected worklog pagination loop for issue %s (v%s), startAt=%s",
                            issue_key,
                            ver,
                            start_at,
                        )
                        break
                    if len(seen_starts) >= max_pages:
                        logger.warning(
                            "Worklog pagination page limit reached for issue %s (v%s): %s pages",
                            issue_key,
                            ver,
                            max_pages,
                        )
                        break
                    seen_starts.add(start_at)

                    params = {"startAt": start_at, "maxResults": 100}

                    # Use dedicated timeout for worklog requests
                    worklog_timeout = getattr(settings, "JIRA_WORKLOG_TIMEOUT", None)
                    if not worklog_timeout:
                        worklog_timeout = getattr(settings, "JIRA_HTTP_TIMEOUT", 60) or 60

                    response = self.http_client.get(
                        endpoint, params=params, timeout=worklog_timeout
                    )
                    response.raise_for_status()

                    # Check content type
                    ctype = (response.headers.get("content-type") or "").lower()
                    if "application/json" not in ctype:
                        try:
                            metrics.inc(
                                "jira_non_json_total", labels={"ep": "worklog", "ver": str(ver)}
                            )
                        except Exception:
                            pass
                        body = (response.text or "")[:200]
                        raise ValueError(f"Non-JSON response ctype={ctype} body={body}")

                    data = response.json()
                    logs = data.get("worklogs", []) if isinstance(data, dict) else []
                    items.extend(logs)

                    if not logs:
                        break

                    response_start_at = data.get("startAt") if isinstance(data, dict) else None
                    current_start_at = (
                        int(response_start_at) if isinstance(response_start_at, int) else start_at
                    )
                    response_max_results = (
                        data.get("maxResults") if isinstance(data, dict) else None
                    )
                    current_max_results = (
                        int(response_max_results)
                        if isinstance(response_max_results, int) and response_max_results > 0
                        else params["maxResults"]
                    )
                    next_start_at = current_start_at + len(logs)
                    total_count = data.get("total") if isinstance(data, dict) else None
                    if isinstance(total_count, int) and next_start_at >= total_count:
                        break
                    if len(logs) < current_max_results:
                        break
                    if next_start_at <= current_start_at:
                        logger.warning(
                            "Non-advancing worklog pagination for issue %s (v%s), breaking at %s",
                            issue_key,
                            ver,
                            current_start_at,
                        )
                        break
                    start_at = next_start_at

                self.circuit_breaker.record_success()
                return items

            except Exception as e:
                last_err = e

                # Metrics for worklog failures/timeouts
                try:
                    if isinstance(e, (Exception,)):  # Generic timeout check
                        if "timeout" in str(type(e).__name__).lower():
                            metrics.inc("jira_worklog_timeout_total", labels={"ver": str(ver)})
                        else:
                            metrics.inc("jira_worklog_fail_total", labels={"ver": str(ver)})
                except Exception:
                    pass

                self.circuit_breaker.record_failure()
                continue

        logger.warning("get_issue_worklogs failed for %s: %s", issue_key, last_err)
        return []

    async def async_get_issue_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Async version of get_issue_worklogs using httpx.

        Args:
            issue_key: Jira issue key

        Returns:
            List of worklog dicts
        """
        if self.circuit_breaker.is_open():
            return []

        versions = self.version_resolver.get_api_versions("default")

        async with httpx.AsyncClient() as client:
            for ver in versions:
                endpoint = f"/rest/api/{ver}/issue/{issue_key}/worklog"
                start_at = 0
                items: List[Dict[str, Any]] = []
                max_pages = max(1, int(getattr(settings, "JIRA_WORKLOG_MAX_PAGES", 2000) or 2000))
                seen_starts = set()

                try:
                    while True:
                        if start_at in seen_starts:
                            logger.warning(
                                "Detected async worklog pagination loop for issue %s (v%s), startAt=%s",
                                issue_key,
                                ver,
                                start_at,
                            )
                            break
                        if len(seen_starts) >= max_pages:
                            logger.warning(
                                "Async worklog pagination page limit reached for issue %s (v%s): %s pages",
                                issue_key,
                                ver,
                                max_pages,
                            )
                            break
                        seen_starts.add(start_at)

                        params = {"startAt": start_at, "maxResults": 100}
                        worklog_timeout = getattr(settings, "JIRA_WORKLOG_TIMEOUT", None) or 60

                        # Build URL and make request
                        url = f"{self.http_client.base_url}{endpoint}"
                        headers = self.http_client.headers()

                        # Prepare auth
                        auth = None
                        if self.http_client.email and self.http_client.api_token:
                            auth = (self.http_client.email, self.http_client.api_token)

                        resp = await client.get(
                            url, params=params, headers=headers, auth=auth, timeout=worklog_timeout
                        )
                        resp.raise_for_status()

                        data = resp.json()
                        logs = data.get("worklogs", []) if isinstance(data, dict) else []
                        items.extend(logs)

                        if not logs:
                            break

                        response_start_at = data.get("startAt") if isinstance(data, dict) else None
                        current_start_at = (
                            int(response_start_at)
                            if isinstance(response_start_at, int)
                            else start_at
                        )
                        response_max_results = (
                            data.get("maxResults") if isinstance(data, dict) else None
                        )
                        current_max_results = (
                            int(response_max_results)
                            if isinstance(response_max_results, int) and response_max_results > 0
                            else params["maxResults"]
                        )
                        next_start_at = current_start_at + len(logs)
                        total_count = data.get("total") if isinstance(data, dict) else None
                        if isinstance(total_count, int) and next_start_at >= total_count:
                            break
                        if len(logs) < current_max_results:
                            break
                        if next_start_at <= current_start_at:
                            logger.warning(
                                "Non-advancing async worklog pagination for issue %s (v%s), breaking at %s",
                                issue_key,
                                ver,
                                current_start_at,
                            )
                            break
                        start_at = next_start_at

                    self.circuit_breaker.record_success()
                    return items

                except httpx.TimeoutException as e:
                    logger.warning(
                        "Async get_issue_worklogs timeout (v%s) for %s: %s", ver, issue_key, e
                    )
                    try:
                        metrics.inc("jira_worklog_timeout_total", labels={"ver": str(ver)})
                    except Exception:
                        pass
                    self.circuit_breaker.record_failure()
                    # Fail fast on timeout to avoid long hanging sync loops.
                    return []
                except Exception as e:
                    logger.warning(
                        "Async get_issue_worklogs (v%s) failed for %s: %s", ver, issue_key, e
                    )
                    self.circuit_breaker.record_failure()
                    continue

        return []

    # Optional helpers for backward compatibility
    def get_active_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """
        Get active sprints for a board.

        Args:
            board_id: Jira board ID

        Returns:
            List of active sprint dicts
        """
        all_sprints = self.list_sprints(board_id)
        return [s for s in all_sprints if s.get("state") == "active"]

    def get_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Alias for get_issue_worklogs (backward compatibility).

        Args:
            issue_key: Jira issue key

        Returns:
            List of worklog dicts
        """
        return self.get_issue_worklogs(issue_key)
