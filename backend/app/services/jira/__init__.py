"""
Jira API client services package.

This package contains specialized services for Jira API integration:
- JiraService: Simplified facade for all Jira operations (main entry point)
- JiraHttpClient: HTTP communication with retry logic
- CircuitBreaker: API resilience pattern
- JiraResponseHandler: Response validation and error detection
- JiraAuthStrategy: Authentication strategies (Basic, Bearer)
- JiraAuthFactory: Factory for creating auth strategies
- JiraApiVersionResolver: API version detection and fallback logic
- JiraProjectService: Project operations (get_project, get_project_issues, list_projects)
- JiraBoardService: Board and sprint operations (list_boards, list_sprints, get_worklogs)

Exceptions:
- JiraAuthError: Authentication/authorization failures
- JiraUnexpectedResponse: Non-JSON or invalid responses

Usage:
    from app.services.jira import JiraService

    jira = JiraService()
    jira.connect(base_url="https://company.atlassian.net",
                 email="user@example.com",
                 api_token="token")

    project = jira.get_project("PROJ")
    issues = jira.get_project_issues("PROJ")
"""

from app.services.jira.jira_service import JiraService
from app.services.jira.http_client import JiraHttpClient
from app.services.jira.circuit_breaker import CircuitBreaker
from app.services.jira.response_handler import (
    JiraResponseHandler,
    JiraAuthError,
    JiraUnexpectedResponse,
)
from app.services.jira.auth_strategy import (
    JiraAuthStrategy,
    BasicAuthStrategy,
    BearerAuthStrategy,
    JiraAuthFactory,
)
from app.services.jira.version_resolver import JiraApiVersionResolver
from app.services.jira.project_service import JiraProjectService
from app.services.jira.board_service import JiraBoardService

__all__ = [
    # Main Facade (primary entry point)
    'JiraService',
    # HTTP Client
    'JiraHttpClient',
    # Resilience
    'CircuitBreaker',
    # Response Handling
    'JiraResponseHandler',
    'JiraAuthError',
    'JiraUnexpectedResponse',
    # Authentication
    'JiraAuthStrategy',
    'BasicAuthStrategy',
    'BearerAuthStrategy',
    'JiraAuthFactory',
    # Version Resolution
    'JiraApiVersionResolver',
    # Project Operations
    'JiraProjectService',
    # Board Operations
    'JiraBoardService',
]
