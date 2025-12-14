"""
Jira API Service - Simplified Facade.

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
"""

import logging
from typing import Dict, Any, List, Optional

from app.core.config import settings
from app.services.jira.http_client import JiraHttpClient
from app.services.jira.circuit_breaker import CircuitBreaker
from app.services.jira.response_handler import JiraResponseHandler, JiraAuthError
from app.services.jira.auth_strategy import JiraAuthFactory
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

        # Services (initialized in connect())
        self.http_client: Optional[JiraHttpClient] = None
        self.circuit_breaker: Optional[CircuitBreaker] = None
        self.response_handler: Optional[JiraResponseHandler] = None
        self.version_resolver: Optional[JiraApiVersionResolver] = None
        self.project_service: Optional[JiraProjectService] = None
        self.board_service: Optional[JiraBoardService] = None

        # Auto-connect if credentials are available
        if settings.JIRA_BASE_URL:
            try:
                self.connect(
                    base_url=settings.JIRA_BASE_URL,
                    email=settings.JIRA_USER_EMAIL,
                    api_token=settings.JIRA_API_TOKEN,
                    use_pat=getattr(settings, 'JIRA_USE_PAT', None)
                )
            except Exception as e:
                logger.warning("Auto-connect to Jira failed: %s", e)

    def connect(
        self,
        base_url: str = None,
        email: str = None,
        api_token: str = None,
        use_pat: Optional[bool] = None
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
        self.base_url = base_url or settings.JIRA_BASE_URL
        self.email = email or settings.JIRA_USER_EMAIL
        self.api_token = api_token or settings.JIRA_API_TOKEN

        # Determine auth type
        if use_pat is None:
            use_pat = getattr(settings, 'JIRA_USE_PAT', False)

        # Set bearer_token for PAT auth
        if use_pat:
            self.bearer_token = self.api_token
        else:
            self.bearer_token = None

        if not self.base_url:
            raise Exception("Jira base URL is required")

        if not self.api_token:
            raise Exception("Jira API token is required")

        # Initialize services
        self._initialize_services()

        # Log connection info
        auth_type = "PAT" if self.bearer_token else "Basic"
        server_type = self.version_resolver.get_server_type_name()
        logger.info("Jira connected: %s [%s auth, %s]",
                   self.base_url, auth_type, server_type)

    def _initialize_services(self):
        """Initialize all services with current connection parameters."""
        # Create HTTP client
        if self.bearer_token:
            self.http_client = JiraHttpClient(
                base_url=self.base_url,
                bearer_token=self.bearer_token
            )
        else:
            self.http_client = JiraHttpClient(
                base_url=self.base_url,
                email=self.email,
                api_token=self.api_token
            )

        # Create circuit breaker
        threshold = getattr(settings, 'JIRA_CB_THRESHOLD', 5)
        sleep_seconds = getattr(settings, 'JIRA_CB_SLEEP_SECONDS', 60)
        enabled = getattr(settings, 'JIRA_CB_ENABLED', False)

        self.circuit_breaker = CircuitBreaker(
            threshold=threshold,
            sleep_seconds=sleep_seconds,
            enabled=enabled
        )

        # Create response handler
        self.response_handler = JiraResponseHandler(
            circuit_breaker=self.circuit_breaker
        )

        # Create version resolver
        self.version_resolver = JiraApiVersionResolver(
            base_url=self.base_url
        )

        # Create project service
        self.project_service = JiraProjectService(
            http_client=self.http_client,
            circuit_breaker=self.circuit_breaker,
            response_handler=self.response_handler,
            version_resolver=self.version_resolver
        )

        # Create board service
        self.board_service = JiraBoardService(
            http_client=self.http_client,
            circuit_breaker=self.circuit_breaker,
            version_resolver=self.version_resolver
        )

    def validate(self) -> bool:
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
        versions = self.version_resolver.get_api_versions('validation')
        attempts = []

        for ver in versions:
            endpoint = f"/rest/api/{ver}/myself"
            try:
                logger.debug("Jira validate: GET %s", endpoint)
                response = self.http_client.get(endpoint)

                # Check for valid JSON response
                ctype = response.headers.get('content-type', '')
                status = response.status_code

                if status == 200 and 'application/json' in ctype.lower():
                    logger.info("Jira validate: OK via %s", endpoint)
                    return True

                attempts.append((endpoint, status, ctype))

            except Exception as e:
                logger.warning("Jira validate (%s) failed: %s", endpoint, e)
                attempts.append((endpoint, 0, str(e)))

        # Try serverInfo as fallback
        for ver in versions:
            endpoint = f"/rest/api/{ver}/serverInfo"
            try:
                response = self.http_client.get(endpoint)
                ctype = response.headers.get('content-type', '')
                status = response.status_code

                if status == 200 and 'application/json' in ctype.lower():
                    logger.info("Jira validate: OK via %s", endpoint)
                    return True

                attempts.append((endpoint, status, ctype))

            except Exception as e:
                attempts.append((endpoint, 0, str(e)))

        # Build error message
        details = []
        for endpoint, status, ctype in attempts:
            if status:
                details.append(f"{endpoint} -> {status} {ctype}")
            else:
                details.append(f"{endpoint} -> {ctype}")

        hint = (
            "Validation failed. "
            "If using Jira Cloud, provide email + API token (Basic auth). "
            "If using Jira Server/DC, use PAT with Bearer auth. "
            "SSO/Proxy may return HTML login pages."
        )
        raise Exception(hint + " Attempts: " + " | ".join(details))

    # ---- Project Operations (delegate to ProjectService) ----

    def get_project(self, project_key: str) -> Dict[str, Any]:
        """
        Get project details from Jira.

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

        return self.project_service.get_project(project_key)

    def get_project_issues(
        self,
        project_key: str,
        max_results: Optional[int] = None
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
        List accessible Jira projects.

        Args:
            query: Optional search query to filter projects

        Returns:
            List of project dicts with key, name, id

        Raises:
            JiraAuthError: If authentication fails
        """
        if not self.project_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.project_service.list_projects(query)

    async def async_get_project_issues(
        self,
        project_key: str,
        max_results: Optional[int] = None
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
        List all boards for a Jira project.

        Args:
            project_key: Jira project key

        Returns:
            List of board dicts (id, name, type, etc.)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.board_service.list_boards_for_project(project_key)

    def list_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """
        List all sprints for a Jira board with pagination.

        Args:
            board_id: Jira board ID

        Returns:
            List of sprint dicts (id, name, state, startDate, endDate, goal)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.board_service.list_sprints(board_id)

    def list_issues_in_sprint(self, sprint_id: int) -> List[Dict[str, Any]]:
        """
        List all issues in a sprint.

        Args:
            sprint_id: Jira sprint ID

        Returns:
            List of issue dicts (key and other fields)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.board_service.list_issues_in_sprint(sprint_id)

    def get_issue_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Get all worklogs (time tracking) for an issue.

        Args:
            issue_key: Jira issue key (e.g., "PROJ-123")

        Returns:
            List of worklog dicts (author, timeSpent, started, comment, etc.)
        """
        if not self.board_service:
            raise Exception("Jira not connected (call connect() first)")

        return self.board_service.get_issue_worklogs(issue_key)

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
