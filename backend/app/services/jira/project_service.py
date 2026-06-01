"""Jira project operations service."""

import logging
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.services.jira.http_client import JiraHttpClient
from app.services.jira.circuit_breaker import CircuitBreaker
from app.services.jira.response_handler import (
    JiraResponseHandler,
    JiraAuthError,
    JiraUnexpectedResponse,
)
from app.services.jira.version_resolver import JiraApiVersionResolver

logger = logging.getLogger(__name__)


class JiraProjectService:
    """
    Handles Jira project-related operations.

    Responsibilities:
    - Fetch project details (get_project)
    - Fetch project issues with pagination (get_project_issues)
    - List accessible projects (list_projects)
    - Async versions of above methods

    All methods use injected dependencies for HTTP, circuit breaker,
    response handling, and API version resolution.
    """

    def __init__(
        self,
        http_client: JiraHttpClient,
        circuit_breaker: CircuitBreaker,
        response_handler: JiraResponseHandler,
        version_resolver: JiraApiVersionResolver,
    ):
        """
        Initialize project service.

        Args:
            http_client: HTTP client for making requests
            circuit_breaker: Circuit breaker for resilience
            response_handler: Response validator
            version_resolver: API version resolver
        """
        self.http_client = http_client
        self.circuit_breaker = circuit_breaker
        self.response_handler = response_handler
        self.version_resolver = version_resolver

    def get_project(self, project_key: str) -> Dict[str, Any]:
        """
        Get project details from Jira.

        Tries appropriate API versions based on server type (Cloud vs Server/DC).
        Falls back from v3 to v2 if needed.

        Args:
            project_key: Jira project key (e.g., "PROJ")

        Returns:
            Dict with project details (key, name, description, lead, url)

        Raises:
            JiraAuthError: If authentication fails
            Exception: If all API versions fail
        """
        if self.circuit_breaker.is_open():
            raise Exception("Jira temporarily disabled (circuit breaker)")

        last_err: Optional[Exception] = None
        versions = self.version_resolver.get_api_versions("default")

        for ver in versions:
            endpoint = f"/rest/api/{ver}/project/{project_key}"
            try:
                logger.debug("Jira get_project: GET %s", endpoint)
                response = self.http_client.get(endpoint)

                # Validate and parse response
                data = self.response_handler.handle_response(endpoint, response)

                # Extract project data
                project = {
                    "key": data.get("key", project_key),
                    "name": data.get("name", project_key),
                    "description": data.get("description", ""),
                    "lead": (data.get("lead") or {}).get("displayName", ""),
                    "url": data.get("self", ""),
                }

                self.circuit_breaker.record_success()
                return project

            except JiraAuthError:
                self.circuit_breaker.record_failure()
                raise

            except Exception as e:
                last_err = e
                logger.warning("Jira get_project (v%s) failed: %s", ver, e)
                self.circuit_breaker.record_failure()

        logger.error("Failed to get project %s: %s", project_key, last_err)
        raise last_err or Exception(f"Failed to get project {project_key}")

    def get_project_issues(
        self, project_key: str, max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get issues for a Jira project with pagination.

        Tries appropriate API versions and handles pagination automatically.

        Args:
            project_key: Jira project key
            max_results: Maximum issues to fetch (default from settings)

        Returns:
            List of issue dicts with all relevant fields

        Raises:
            JiraAuthError: If authentication fails
            JiraUnexpectedResponse: If response is invalid
        """
        if self.circuit_breaker.is_open():
            logger.warning("Circuit breaker open for Jira, returning empty data")
            return []

        max_results = max_results or settings.JIRA_MAX_RESULTS
        page_size = min(settings.JIRA_PAGE_SIZE, max_results)

        jql = f"project={project_key} ORDER BY created DESC"
        fields = [
            "summary",
            "status",
            "issuetype",
            "priority",
            "assignee",
            "timetracking",
            "timeoriginalestimate",
            "timespent",
            "timeestimate",
            "created",
            "updated",
            "resolutiondate",
            "duedate",
            "labels",
            "components",
        ]

        versions = self.version_resolver.get_api_versions("default")
        last_err: Optional[Exception] = None

        for ver in versions:
            endpoint = f"/rest/api/{ver}/search"
            start_at = 0
            all_issues: List[Dict[str, Any]] = []

            try:
                while len(all_issues) < max_results:
                    current_page_size = min(page_size, max_results - len(all_issues))
                    params: Dict[str, str | int | float | bool | None] = {
                        "jql": jql,
                        "maxResults": int(current_page_size),
                        "startAt": int(start_at),
                        "fields": ",".join(fields),
                    }

                    logger.debug("Jira search issues (v%s): GET %s", ver, endpoint)

                    # Use shorter timeout for search queries
                    response = self.http_client.get(endpoint, params=params, timeout=20)

                    # Validate response
                    data = self.response_handler.handle_response(endpoint, response)

                    # Check for Jira error messages
                    if isinstance(data, dict):
                        err_list = data.get("errorMessages") or []
                        warn_list = data.get("warningMessages") or []
                        if err_list:
                            msg = "; ".join(str(x) for x in err_list)
                            raise JiraUnexpectedResponse(f"Jira search error: {msg}")

                        lower_warns = " ".join(str(x).lower() for x in warn_list)
                        if "does not exist" in lower_warns and "project" in lower_warns:
                            raise JiraUnexpectedResponse(
                                f"Project '{project_key}' not found or not visible"
                            )

                    issues = data.get("issues", [])
                    total = data.get("total", len(issues))

                    # Log progress for large datasets
                    if total > 100:
                        logger.info(
                            f"Fetching issues for {project_key}: "
                            f"{start_at + len(issues)}/{min(total, max_results)}"
                        )

                    # Transform issues
                    for issue in issues:
                        all_issues.append(self._transform_issue(issue))

                    start_at += len(issues)
                    if start_at >= total or len(issues) == 0:
                        break

                logger.info(
                    "Jira search (v%s): project=%s fetched_total=%d",
                    ver,
                    project_key,
                    len(all_issues),
                )
                self.circuit_breaker.record_success()
                return all_issues

            except JiraAuthError:
                self.circuit_breaker.record_failure()
                raise

            except Exception as e:
                last_err = e
                logger.warning("Jira search (v%s) failed for %s: %s", ver, project_key, e)
                self.circuit_breaker.record_failure()

        logger.error("Failed to fetch issues for project %s: %s", project_key, last_err)
        if last_err:
            raise last_err
        raise RuntimeError(f"Failed to fetch issues for {project_key}: unknown error")

    def list_projects(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List accessible Jira projects.

        Returns projects the authenticated user can access.

        Args:
            query: Optional search query to filter projects

        Returns:
            List of project dicts with key, name, id

        Raises:
            JiraAuthError: If authentication fails
            JiraUnexpectedResponse: If response is invalid
        """
        if self.circuit_breaker.is_open():
            return []

        # Try v3 for Cloud instances (has better pagination)
        if not self.version_resolver.is_server():
            try:
                endpoint = "/rest/api/3/project/search"
                logger.debug("Jira list_projects v3: GET %s", endpoint)

                response = self.http_client.get(endpoint)
                data = self.response_handler.handle_response("project_search_v3", response)

                values = data.get("values", []) if isinstance(data, dict) else []
                items = [
                    {"key": p.get("key"), "name": p.get("name"), "id": p.get("id")} for p in values
                ]

                if query:
                    items = self._filter_projects(items, query)

                self.circuit_breaker.record_success()
                return items

            except JiraAuthError:
                self.circuit_breaker.record_failure()
                raise

            except JiraUnexpectedResponse as e:
                logger.warning("Jira list_projects v3 unexpected response: %s", e)
                # Fall through to v2

            except Exception as e:
                logger.warning("Jira list_projects v3 failed: %s", e)
                # Fall through to v2

        # Try v2 (works for both Cloud and Server/DC)
        try:
            endpoint = "/rest/api/2/project"
            logger.debug("Jira list_projects v2: GET %s", endpoint)

            response = self.http_client.get(endpoint)
            data = self.response_handler.handle_response("project_list_v2", response)

            items = [
                {"key": p.get("key"), "name": p.get("name"), "id": p.get("id")}
                for p in (data or [])
            ]

            if query:
                items = self._filter_projects(items, query)

            self.circuit_breaker.record_success()
            return items

        except JiraAuthError:
            self.circuit_breaker.record_failure()
            raise

        except JiraUnexpectedResponse as e:
            logger.error("Jira list_projects v2 unexpected response: %s", e)
            self.circuit_breaker.record_failure()
            raise

        except Exception as e:
            logger.error("Jira list_projects v2 failed: %s", e)
            self.circuit_breaker.record_failure()
            raise JiraUnexpectedResponse(f"Failed to fetch Jira projects: {e}") from e

    async def async_get_project_issues(
        self, project_key: str, max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Async version of get_project_issues using httpx.

        Args:
            project_key: Jira project key
            max_results: Maximum issues to fetch

        Returns:
            List of issue dicts
        """
        if self.circuit_breaker.is_open():
            logger.warning("Circuit breaker open for Jira, returning empty data")
            return []

        logger.info(
            "Jira async: fetching issues for project=%s (mode=%s)",
            project_key,
            self.version_resolver.get_server_type_name(),
        )

        max_results = max_results or settings.JIRA_MAX_RESULTS
        page_size = min(settings.JIRA_PAGE_SIZE, max_results)

        jql = f"project={project_key} ORDER BY created DESC"
        fields = [
            "summary",
            "status",
            "issuetype",
            "priority",
            "assignee",
            "timetracking",
            "timeoriginalestimate",
            "timespent",
            "timeestimate",
            "created",
            "updated",
            "resolutiondate",
            "duedate",
            "labels",
            "components",
        ]

        versions = self.version_resolver.get_api_versions("default")

        async with httpx.AsyncClient() as client:
            for ver in versions:
                endpoint = f"/rest/api/{ver}/search"
                start_at = 0
                all_issues: List[Dict[str, Any]] = []

                try:
                    while len(all_issues) < max_results:
                        current_page_size = min(page_size, max_results - len(all_issues))
                        params: Dict[str, str | int | float | bool | None] = {
                            "jql": jql,
                            "maxResults": int(current_page_size),
                            "startAt": int(start_at),
                            "fields": ",".join(fields),
                        }

                        logger.debug("Jira async search (v%s): GET %s", ver, endpoint)

                        # Build URL and make request
                        url = f"{self.http_client.base_url}{endpoint}"
                        headers = self.http_client.headers()

                        # Prepare auth
                        auth = None
                        if self.http_client.email and self.http_client.api_token:
                            auth = (self.http_client.email, self.http_client.api_token)

                        resp = await client.get(
                            url, params=params, headers=headers, auth=auth, timeout=20
                        )
                        resp.raise_for_status()

                        data = resp.json()

                        # Check for errors
                        if isinstance(data, dict):
                            err_list = data.get("errorMessages") or []
                            if err_list:
                                msg = "; ".join(str(x) for x in err_list)
                                raise JiraUnexpectedResponse(f"Jira search error: {msg}")

                        issues = data.get("issues", [])
                        total = data.get("total", len(issues))

                        if total > 100:
                            logger.info(
                                f"Fetching issues for {project_key}: "
                                f"{start_at + len(issues)}/{min(total, max_results)}"
                            )

                        for issue in issues:
                            transformed = self._transform_issue(issue)
                            if transformed.get("key"):
                                all_issues.append(transformed)

                        start_at += len(issues)
                        if start_at >= total or len(issues) == 0:
                            break

                    logger.info(
                        "Jira async search (v%s): project=%s fetched_total=%d",
                        ver,
                        project_key,
                        len(all_issues),
                    )
                    self.circuit_breaker.record_success()
                    return all_issues

                except httpx.HTTPStatusError as e:
                    logger.error(
                        "Jira async search (v%s) HTTP error for %s: status=%s",
                        ver,
                        project_key,
                        e.response.status_code,
                    )
                    self.circuit_breaker.record_failure()
                    continue

                except httpx.TimeoutException as e:
                    logger.error("Jira async search (v%s) timeout for %s: %s", ver, project_key, e)
                    self.circuit_breaker.record_failure()
                    continue

                except Exception as e:
                    logger.error(
                        "Jira async search (v%s) unexpected error for %s: %s (type=%s)",
                        ver,
                        project_key,
                        e,
                        type(e).__name__,
                        exc_info=True,
                    )
                    self.circuit_breaker.record_failure()
                    continue

        logger.error("Failed to fetch issues for project %s (all API versions failed)", project_key)
        return []

    def _transform_issue(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform raw Jira issue to internal format.

        Args:
            issue: Raw issue dict from Jira API

        Returns:
            Transformed issue dict
        """
        issue_dict = issue if isinstance(issue, dict) else {}
        fields_raw = issue_dict.get("fields")
        f = fields_raw if isinstance(fields_raw, dict) else {}

        def get_name(value: Any) -> Optional[str]:
            if isinstance(value, dict):
                name = value.get("name")
                return name if isinstance(name, str) else None
            return None

        components: List[str] = []
        for c in f.get("components") or []:
            if isinstance(c, dict):
                component_name = c.get("name")
                if isinstance(component_name, str) and component_name:
                    components.append(component_name)

        assignee = f.get("assignee") if isinstance(f.get("assignee"), dict) else {}

        def hours(val: Optional[int]) -> Optional[float]:
            """Convert seconds to hours."""
            try:
                return round((val or 0) / 3600, 2) if val is not None else None
            except Exception:
                return None

        return {
            "jira_id": issue_dict.get("id"),
            "key": issue_dict.get("key"),
            "summary": f.get("summary"),
            "description": None,
            "task_type": get_name(f.get("issuetype")),
            "status": get_name(f.get("status")),
            "priority": get_name(f.get("priority")),
            "assignee_email": assignee.get("emailAddress"),
            "assignee_name": assignee.get("displayName"),
            "estimate_hours": hours(f.get("timeoriginalestimate")),
            "spent_hours": hours(f.get("timespent")),
            "remaining_hours": hours(f.get("timeestimate")),
            "created_date": f.get("created"),
            "updated_date": f.get("updated"),
            "resolved_date": f.get("resolutiondate"),
            "due_date": f.get("duedate"),
            "labels": f.get("labels") if isinstance(f.get("labels"), list) else [],
            "components": components,
            "is_blocker": False,
            "blocked_by": [],
            "blocks": [],
        }

    def _filter_projects(self, items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
        """
        Filter projects by search query.

        Args:
            items: List of project dicts
            query: Search query

        Returns:
            Filtered list of projects
        """
        q = query.lower()
        return [
            i
            for i in items
            if (i.get("key") and q in i["key"].lower())
            or (i.get("name") and q in i["name"].lower())
        ]
