"""
Jira API Service - Simplified Facade with Caching.

This facade provides a simplified, backward-compatible interface to the
refactored Jira services. It initializes and coordinates:
- JiraHttpClient: HTTP communication
- CircuitBreaker: API resilience
- JiraResponseHandler: Response validation
- JiraAuthStrategy: Authentication
- JiraApiVersionResolver: Version detection
- JiraProjectService: Project operations
- JiraBoardService: Board/sprint operations

All business logic has been extracted to specialized services.
This facade simply delegates calls and maintains backward compatibility.

Caching Strategy (per PERFORMANCE_RECOMMENDATIONS.md):
- get_project(): COLD tier (30 min) - project metadata rarely changes
- list_projects(): STATIC tier (1 hour) - project list very stable
- list_boards_for_project(): COLD tier (30 min) - boards rarely added
- list_sprints(): WARM tier (5 min) - sprints can change during planning
- list_issues_in_sprint(): HOT tier (60 sec) - issues move frequently
- get_issue_worklogs(): WARM tier (5 min) - worklogs added during work
"""

import logging
from typing import Dict, Any, List, Optional

from requests.auth import HTTPBasicAuth

from app.core.config import settings
from app.core.cache_enhanced import (
    CacheTier,
    JiraCacheKeys,
    sync_cache_get,
    sync_cache_set,
    sync_cache_invalidate_jira,
)
from app.services.jira.http_client import JiraHttpClient
from app.services.jira.circuit_breaker import CircuitBreaker
from app.services.jira.response_handler import JiraResponseHandler
from app.services.jira.version_resolver import JiraApiVersionResolver
from app.services.jira.project_service import JiraProjectService
from app.services.jira.board_service import JiraBoardService

logger = logging.getLogger(__name__)


class JiraService:
    """
    Simplified facade for Jira API operations.

    This class maintains backward compatibility with the original JiraService
    while delegating all operations to specialized services.

    Usage:
        jira = JiraService()
        jira.connect(base_url="https://company.atlassian.net",
                     email="user@example.com",
                     api_token="token")

        # Or with PAT:
        jira.connect(base_url="https://jira.company.com",
                     api_token="PAT_token",
                     use_pat=True)

        # Validate connection
        jira.validate()

        # Use the service
        project = jira.get_project("PROJ")
        issues = jira.get_project_issues("PROJ")
    """

    def __init__(self):
        """Initialize the facade without connection (call connect() to setup)."""
        # Connection parameters
        self.base_url: Optional[str] = None
        self.email: Optional[str] = None
        self.api_token: Optional[str] = None
        self.bearer_token: Optional[str] = None
        self.auth: Optional[HTTPBasicAuth] = None

        # Services (initialized in connect())
        self.http_client: Optional[JiraHttpClient] = None
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.response_handler: Optional[JiraResponseHandler] = None
        self.version_resolver: Optional[JiraApiVersionResolver] = None
        self.project_service: Optional[JiraProjectService] = None
        self.board_service: Optional[JiraBoardService] = None

        # Auto-connect if credentials are available and not explicitly skipped
        if settings.JIRA_BASE_URL and not getattr(settings, "SKIP_SERVICE_AUTOCONNECT", False):
            try:
                self.connect(
                    base_url=settings.JIRA_BASE_URL,
                    email=settings.JIRA_EMAIL,
                    api_token=settings.JIRA_API_TOKEN,
                    use_pat=getattr(settings, "JIRA_USE_PAT", None),
                )
            except Exception as e:
                logger.warning("Auto-connect to Jira failed: %s", e)

    def connect(
        self,
        base_url: Optional[str] = None,
        email: Optional[str] = None,
        api_token: Optional[str] = None,
        use_pat: Optional[bool] = None,
    ):
        """
        Connect to Jira with credentials.

        Args:
            base_url: Jira instance URL (e.g., https://company.atlassian.net)
            email: User email for Basic auth (Cloud)
            api_token: API token or PAT
            use_pat: If True, use PAT (Bearer auth). If False/None, use Basic auth.

        Raises:
            Exception: If credentials are invalid or connection fails
        """
        # Set connection parameters
        self.base_url = (base_url or settings.JIRA_BASE_URL or "").rstrip("/") or None
        self.email = email or settings.JIRA_EMAIL
        self.api_token = api_token or settings.JIRA_API_TOKEN

        # Determine auth type with sensible defaults:
        # - force PAT if configured
        # - respect explicit use_pat flag or settings override
        # - fallback: PAT when no email provided
        force_pat = getattr(settings, "JIRA_FORCE_PAT", False)
        default_use_pat = getattr(settings, "JIRA_USE_PAT", None)

        if force_pat:
            use_pat = True
        elif use_pat is None:
            use_pat = default_use_pat if default_use_pat is not None else not bool(self.email)

        # Reset auth state then set bearer_token for PAT auth
        self.auth = None
        if use_pat:
            self.bearer_token = self.api_token
        else:
            self.bearer_token = None
            self.auth = (
                HTTPBasicAuth(self.email, self.api_token) if self.email and self.api_token else None
            )

        if not self.base_url:
            raise Exception("Jira base URL is required")

        if not self.api_token:
            raise Exception("Jira API token is required")

        if not use_pat and not self.email:
            raise Exception("Jira email is required for Basic auth")

        # Initialize services
        self._initialize_services()

        # Log connection info
        auth_type = "PAT" if self.bearer_token else "Basic"
        server_type = self._require_version_resolver().get_server_type_name()
        logger.info("Jira connected: %s [%s auth, %s]", self.base_url, auth_type, server_type)

    def _require_version_resolver(self) -> JiraApiVersionResolver:
        if not self.version_resolver:
            raise Exception("Jira version resolver not initialized")
        return self.version_resolver

    def _initialize_services(self):
        """Initialize all services with current connection parameters."""
        if self.base_url is None:
            raise Exception("Jira base URL is required before initializing services")
        base_url: str = self.base_url
        # Create HTTP client (supports both Basic and PAT)
        self.http_client = JiraHttpClient(
            base_url=base_url,
            auth=self.auth,
            bearer_token=self.bearer_token,
            email=self.email,
            api_token=self.api_token,
        )

        # Create circuit breaker
        threshold = getattr(settings, "JIRA_CB_THRESHOLD", 5)
        sleep_seconds = getattr(settings, "JIRA_CB_SLEEP_SECONDS", 60)
        enabled = getattr(settings, "JIRA_CB_ENABLED", False)

        self.circuit_breaker = CircuitBreaker(
            threshold=threshold, sleep_seconds=sleep_seconds, enabled=enabled
        )

        # Create response handler
        self.response_handler = JiraResponseHandler()

        # Create version resolver
        self.version_resolver = JiraApiVersionResolver(base_url=base_url)

        # Create project service
        self.project_service = JiraProjectService(
            http_client=self.http_client,
            circuit_breaker=self.circuit_breaker,
            response_handler=self.response_handler,
            version_resolver=self.version_resolver,
        )

        # Create board service
        self.board_service = JiraBoardService(
            http_client=self.http_client,
            circuit_breaker=self.circuit_breaker,
            version_resolver=self.version_resolver,
        )

    def _base_url_discovery_candidates(self) -> List[str]:
        """
        Generate alternate Jira base URL candidates for environments where
        Jira may be exposed both with and without '/jira' context path.
        """
        if not self.base_url:
            return []

        base = self.base_url.rstrip("/")
        lower_base = base.lower()
        candidates: List[str] = []

        if lower_base.endswith("/jira"):
            candidate = base[: -len("/jira")].rstrip("/")
            if candidate:
                candidates.append(candidate)
        else:
            candidates.append(f"{base}/jira")

        # Preserve order and uniqueness.
        seen: set[str] = set()
        result: List[str] = []
        for candidate in candidates:
            normalized = candidate.rstrip("/")
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result

    def validate(self, allow_base_url_discovery: bool = True) -> bool:
        """
        Validate current Jira credentials.

        Tries to call /rest/api/{version}/myself to verify authentication.

        Returns:
            True if credentials are valid

        Raises:
            Exception: If validation fails with details
            JiraAuthError: If authentication fails
        """
        if not self.base_url or not self.api_token:
            raise Exception("Jira not configured")

        if not self.http_client:
            raise Exception("Jira not connected (call connect() first)")

        # Try validation endpoints with appropriate versions
        versions = self._require_version_resolver().get_api_versions("validation")
        attempts = []

        for ver in versions:
            endpoint = f"/rest/api/{ver}/myself"
            try:
                logger.debug("Jira validate: GET %s", endpoint)
                response = self.http_client.get(endpoint)

                # Check for valid JSON response
                ctype = response.headers.get("content-type", "")
                status = response.status_code

                if status == 200 and "application/json" in ctype.lower():
                    logger.info("Jira validate: OK via %s", endpoint)
                    return True

                # Capture auth-related hints from Jira/SSO/proxies without leaking credentials.
                seraph_reason = response.headers.get("x-seraph-loginreason", "")
                ausername = response.headers.get("x-ausername", "")
                www_auth = response.headers.get("www-authenticate", "")
                meta_parts = [ctype]
                extras = []
                if seraph_reason:
                    extras.append(f"seraph={seraph_reason}")
                if ausername:
                    extras.append(f"user={ausername}")
                if www_auth:
                    extras.append("www-auth=present")
                meta = f"{ctype} ({', '.join(extras)})" if extras else ctype
                attempts.append((endpoint, status, meta))

                if status >= 400:
                    snippet = (
                        (response.text or "")[:200].replace("\r", " ").replace("\n", " ").strip()
                    )
                    if snippet:
                        logger.info(
                            "Jira validate: non-OK response via %s -> %s (%s): %s",
                            endpoint,
                            status,
                            meta_parts[0],
                            snippet,
                        )

            except Exception as e:
                logger.warning("Jira validate (%s) failed: %s", endpoint, e)
                attempts.append((endpoint, 0, str(e)))

        # Try serverInfo as fallback
        for ver in versions:
            endpoint = f"/rest/api/{ver}/serverInfo"
            try:
                response = self.http_client.get(endpoint)
                ctype = response.headers.get("content-type", "")
                status = response.status_code

                if status == 200 and "application/json" in ctype.lower():
                    logger.info("Jira validate: OK via %s", endpoint)
                    return True

                seraph_reason = response.headers.get("x-seraph-loginreason", "")
                ausername = response.headers.get("x-ausername", "")
                www_auth = response.headers.get("www-authenticate", "")
                extras = []
                if seraph_reason:
                    extras.append(f"seraph={seraph_reason}")
                if ausername:
                    extras.append(f"user={ausername}")
                if www_auth:
                    extras.append("www-auth=present")
                meta = f"{ctype} ({', '.join(extras)})" if extras else ctype
                attempts.append((endpoint, status, meta))

                if status >= 400:
                    snippet = (
                        (response.text or "")[:200].replace("\r", " ").replace("\n", " ").strip()
                    )
                    if snippet:
                        logger.info(
                            "Jira validate: non-OK response via %s -> %s (%s): %s",
                            endpoint,
                            status,
                            ctype,
                            snippet,
                        )

            except Exception as e:
                attempts.append((endpoint, 0, str(e)))

        # Build error message
        details = []
        for endpoint, status, ctype in attempts:
            if status:
                details.append(f"{endpoint} -> {status} {ctype}")
            else:
                details.append(f"{endpoint} -> {ctype}")

        # Optional fallback: auto-discover alternate base URL shape.
        if allow_base_url_discovery and not getattr(settings, "JIRA_DISABLE_DISCOVERY", False):
            original_base_url = self.base_url
            original_email = self.email
            original_api_token = self.api_token
            original_use_pat = self.bearer_token is not None
            discovery_failures: List[str] = []

            for candidate_base_url in self._base_url_discovery_candidates():
                try:
                    logger.info(
                        "Jira validate: trying base URL discovery candidate %s",
                        candidate_base_url,
                    )
                    self.connect(
                        base_url=candidate_base_url,
                        email=original_email,
                        api_token=original_api_token,
                        use_pat=original_use_pat,
                    )
                    if self.validate(allow_base_url_discovery=False):
                        logger.info(
                            "Jira validate: base URL discovery succeeded (%s -> %s)",
                            original_base_url,
                            candidate_base_url,
                        )
                        return True
                except Exception as discovery_exc:
                    discovery_failures.append(f"{candidate_base_url}: {discovery_exc}")

            # Restore original connection state if discovery attempts failed.
            try:
                if original_base_url:
                    self.connect(
                        base_url=original_base_url,
                        email=original_email,
                        api_token=original_api_token,
                        use_pat=original_use_pat,
                    )
            except Exception:
                pass

            if discovery_failures:
                details.extend([f"discovery({entry})" for entry in discovery_failures])

        hint = (
            "Validation failed. "
            "If using Jira Cloud, provide email + API token (Basic auth). "
            "If using Jira Server/DC, use PAT with Bearer auth. "
            "SSO/Proxy may return HTML login pages."
        )
        raise Exception(hint + " Attempts: " + " | ".join(details))

    # ---- Legacy/compat helpers ----

    def _normalize_endpoint(self, url_or_endpoint: str) -> str:
        """
        Normalize endpoint or full URL to an endpoint suitable for JiraHttpClient.
        """
        if not url_or_endpoint:
            return url_or_endpoint

        if self.base_url and url_or_endpoint.startswith(self.base_url):
            url_or_endpoint = url_or_endpoint[len(self.base_url) :]

        if url_or_endpoint.startswith(("http://", "https://")):
            return url_or_endpoint

        if not url_or_endpoint.startswith("/"):
            url_or_endpoint = f"/{url_or_endpoint}"
        return url_or_endpoint

    def _headers(self) -> Dict[str, str]:
        """Backward-compatible headers helper used by older call-sites."""
        if not self.http_client:
            raise Exception("Jira not connected (call connect() first)")
        return self.http_client.headers()

    def _get(self, url: str, **kwargs):
        """Backward-compatible GET helper used by older call-sites."""
        if not self.http_client:
            raise Exception("Jira not connected (call connect() first)")
        endpoint = self._normalize_endpoint(url)
        return self.http_client.get(endpoint, **kwargs)

    def _handle_response(self, endpoint: str, response):
        """
        Backward-compatible response handler wrapper (used in legacy tests).
        """
        if not self.response_handler:
            self.response_handler = JiraResponseHandler()
        return self.response_handler.handle_response(endpoint, response)

    def status(self) -> Dict[str, Any]:
        """Lightweight status payload reused by health/Jira endpoints."""
        mode = "none"
        if self.bearer_token:
            mode = "PAT"
        elif self.auth:
            mode = "Basic"

        return {
            "configured": bool(self.base_url and (self.bearer_token or self.auth)),
            "base_url": self.base_url,
            "auth_mode": mode,
        }

    # ---- Project Operations (delegate to ProjectService) ----

    def get_project(self, project_key: str) -> Dict[str, Any]:
        """
        Get project details from Jira (cached for 30 minutes).

        Args:
            project_key: Jira project key (e.g., "PROJ")

        Returns:
            Dict with project details (key, name, description, lead, url)

        Raises:
            JiraAuthError: If authentication fails
            Exception: If project fetch fails
        """
        if not self.project_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.project(project_key)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for project %s", project_key)
            return cached

        # Fetch from JIRA
        result = self.project_service.get_project(project_key)

        # Cache successful result
        if result:
            sync_cache_set(cache_key, result, CacheTier.COLD)  # 30 min

        return result

    def get_project_issues(
        self, project_key: str, max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get issues for a Jira project with pagination.

        Args:
            project_key: Jira project key
            max_results: Maximum issues to fetch (default from settings)

        Returns:
            List of issue dicts with all relevant fields

        Raises:
            JiraAuthError: If authentication fails
        """
        if not self.project_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.project_service.get_project_issues(project_key, max_results)

    def list_projects(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List accessible Jira projects (cached for 1 hour).

        Args:
            query: Optional search query to filter projects

        Returns:
            List of project dicts with key, name, id

        Raises:
            JiraAuthError: If authentication fails
        """
        if not self.project_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.project_list(query)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for projects list (query=%s)", query)
            return cached

        # Fetch from JIRA
        result = self.project_service.list_projects(query)

        # Cache successful result
        if result:
            sync_cache_set(cache_key, result, CacheTier.STATIC)  # 1 hour

        return result

    async def async_get_project_issues(
        self, project_key: str, max_results: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Async version of get_project_issues.

        Args:
            project_key: Jira project key
            max_results: Maximum issues to fetch

        Returns:
            List of issue dicts
        """
        if not self.project_service:
            raise Exception("Jira not connected (call connect() first)")

        return await self.project_service.async_get_project_issues(project_key, max_results)

    # ---- Board Operations (delegate to BoardService) ----

    def list_boards_for_project(self, project_key: str) -> List[Dict[str, Any]]:
        """
        List all boards for a Jira project (cached for 30 minutes).

        Args:
            project_key: Jira project key

        Returns:
            List of board dicts (id, name, type, etc.)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.boards(project_key)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for boards (project=%s)", project_key)
            return cached

        # Fetch from JIRA
        result = self.board_service.list_boards_for_project(project_key)

        # Cache successful result
        if result:
            sync_cache_set(cache_key, result, CacheTier.COLD)  # 30 min

        return result

    def list_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """
        List all sprints for a Jira board with pagination (cached for 5 minutes).

        Args:
            board_id: Jira board ID

        Returns:
            List of sprint dicts (id, name, state, startDate, endDate, goal)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.sprints(board_id)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for sprints (board=%d)", board_id)
            return cached

        # Fetch from JIRA
        result = self.board_service.list_sprints(board_id)

        # Cache successful result
        if result:
            sync_cache_set(cache_key, result, CacheTier.WARM)  # 5 min

        return result

    def list_issues_in_sprint(self, sprint_id: int) -> List[Dict[str, Any]]:
        """
        List all issues in a sprint (cached for 60 seconds).

        Args:
            sprint_id: Jira sprint ID

        Returns:
            List of issue dicts (key and other fields)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.sprint_issues(sprint_id)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for sprint issues (sprint=%d)", sprint_id)
            return cached

        # Fetch from JIRA
        result = self.board_service.list_issues_in_sprint(sprint_id)

        # Cache successful result
        if result:
            sync_cache_set(cache_key, result, CacheTier.HOT)  # 60 sec

        return result

    def get_issue_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Get all worklogs (time tracking) for an issue (cached for 5 minutes).

        Args:
            issue_key: Jira issue key (e.g., "PROJ-123")

        Returns:
            List of worklog dicts (author, timeSpent, started, comment, etc.)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        # Check cache first
        cache_key = JiraCacheKeys.worklogs(issue_key)
        cached = sync_cache_get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for worklogs (issue=%s)", issue_key)
            return cached

        # Fetch from JIRA
        result = self.board_service.get_issue_worklogs(issue_key)

        # Cache successful result (even empty list is valid)
        sync_cache_set(cache_key, result, CacheTier.WARM)  # 5 min

        return result

    async def async_get_issue_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Async version of get_issue_worklogs.

        Args:
            issue_key: Jira issue key

        Returns:
            List of worklog dicts
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return await self.board_service.async_get_issue_worklogs(issue_key)

    # ---- Convenience Methods (backward compatibility) ----

    def get_active_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """
        Get active sprints for a board.

        Args:
            board_id: Jira board ID

        Returns:
            List of active sprint dicts
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.board_service.get_active_sprints(board_id)

    def get_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Alias for get_issue_worklogs (backward compatibility).

        Args:
            issue_key: Jira issue key

        Returns:
            List of worklog dicts
        """
        return self.get_issue_worklogs(issue_key)

    # ---- Cache Management ----

    def invalidate_cache(self) -> int:
        """
        Invalidate all JIRA cache entries.

        Call this after a sync operation to ensure fresh data on next request.

        Returns:
            Number of cache entries invalidated
        """
        return sync_cache_invalidate_jira()
