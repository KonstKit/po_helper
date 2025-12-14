"""Authentication strategies for Jira API using Strategy Pattern."""

from abc import ABC, abstractmethod
from typing import Dict

from requests.auth import HTTPBasicAuth


class JiraAuthStrategy(ABC):
    """
    Abstract authentication strategy for Jira API.

    Implements Strategy Pattern allowing different authentication methods
    to be swapped without changing client code.
    """

    @abstractmethod
    def apply_auth(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Apply authentication to request headers.

        Args:
            headers: Existing request headers

        Returns:
            Headers with authentication applied
        """
        pass

    @abstractmethod
    def get_requests_auth(self):
        """
        Get authentication object for requests library.

        Returns:
            Auth object for requests (HTTPBasicAuth, None, etc.)
        """
        pass

    @abstractmethod
    def auth_type(self) -> str:
        """
        Get authentication type name.

        Returns:
            String describing auth type (e.g., 'Basic', 'Bearer')
        """
        pass


class BasicAuthStrategy(JiraAuthStrategy):
    """
    Basic authentication strategy using email + API token.

    Used for Jira Cloud with email-based authentication.
    """

    def __init__(self, email: str, api_token: str):
        """
        Initialize Basic authentication.

        Args:
            email: User email address
            api_token: Jira API token
        """
        self.email = email
        self.api_token = api_token
        self._auth = HTTPBasicAuth(email, api_token)

    def apply_auth(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Basic auth is handled by requests library, no header modification needed.

        Args:
            headers: Existing request headers

        Returns:
            Unmodified headers (auth applied via requests auth parameter)
        """
        return headers

    def get_requests_auth(self):
        """
        Get HTTPBasicAuth object for requests.

        Returns:
            HTTPBasicAuth instance
        """
        return self._auth

    def auth_type(self) -> str:
        """Get authentication type name."""
        return "Basic"

    def __repr__(self) -> str:
        return f"BasicAuthStrategy(email={self.email})"


class BearerAuthStrategy(JiraAuthStrategy):
    """
    Bearer token authentication strategy using Personal Access Token (PAT).

    Used for:
    - Jira Server/Data Center
    - Jira Cloud with PAT (no email required)
    """

    def __init__(self, token: str):
        """
        Initialize Bearer token authentication.

        Args:
            token: Personal Access Token or Bearer token
        """
        self.token = token

    def apply_auth(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Add Bearer token to Authorization header.

        Args:
            headers: Existing request headers

        Returns:
            Headers with Authorization: Bearer <token>
        """
        if 'Authorization' not in headers:
            headers['Authorization'] = f"Bearer {self.token}"
        return headers

    def get_requests_auth(self):
        """
        Bearer auth uses headers, not requests auth parameter.

        Returns:
            None (auth handled via headers)
        """
        return None

    def auth_type(self) -> str:
        """Get authentication type name."""
        return "Bearer"

    def __repr__(self) -> str:
        return f"BearerAuthStrategy(token=***{self.token[-4:] if len(self.token) > 4 else '***'})"


class JiraAuthFactory:
    """
    Factory for creating authentication strategies.

    Simplifies strategy selection based on available credentials.
    """

    @staticmethod
    def create_auth(
        email: str = None,
        api_token: str = None,
        bearer_token: str = None,
        use_pat: bool = None,
    ) -> JiraAuthStrategy:
        """
        Create appropriate authentication strategy.

        Args:
            email: User email (for Basic auth)
            api_token: API token
            bearer_token: Bearer/PAT token
            use_pat: Force PAT mode (Bearer auth)

        Returns:
            JiraAuthStrategy instance

        Raises:
            ValueError: If credentials are insufficient

        Examples:
            # Bearer auth with PAT
            auth = JiraAuthFactory.create_auth(bearer_token="abc123")

            # Basic auth with email + token
            auth = JiraAuthFactory.create_auth(email="user@example.com", api_token="abc123")

            # Auto-detect (prefer Bearer if no email)
            auth = JiraAuthFactory.create_auth(api_token="abc123", use_pat=True)
        """
        # Explicit Bearer token provided
        if bearer_token:
            return BearerAuthStrategy(bearer_token)

        # Force PAT mode or no email provided
        if use_pat or not email:
            if not api_token:
                raise ValueError("API token required for PAT/Bearer authentication")
            return BearerAuthStrategy(api_token)

        # Basic auth (email + token)
        if email and api_token:
            return BasicAuthStrategy(email, api_token)

        raise ValueError("Insufficient credentials for authentication")
