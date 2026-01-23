"""Jira API version detection and resolution."""

import logging
from typing import Optional, Tuple, Union

logger = logging.getLogger(__name__)


class JiraApiVersionResolver:
    """
    Handles Jira API version detection and fallback logic.

    Jira Cloud supports API v3, v2, and 'latest'
    Jira Server/DC only supports API v2 and 'latest' (no v3)

    This service determines which API versions to try based on the detected
    server type and caches the result to avoid repeated detection.

    Responsibilities:
    - Detect server type (Jira Cloud vs Server/DC) based on URL patterns
    - Provide appropriate API version sequences for different endpoint types
    - Cache server type detection for performance
    """

    def __init__(self, base_url: str):
        """
        Initialize version resolver.

        Args:
            base_url: Jira base URL (e.g., "https://company.atlassian.net")
        """
        self.base_url = base_url
        self._is_server_cache: Optional[bool] = None

    def is_server(self) -> bool:
        """
        Detect if this is a Jira Server/DC instance (cached).

        Returns:
            True if Server/DC, False if Cloud
        """
        if self._is_server_cache is None:
            self._is_server_cache = self._detect_server_type()
            logger.debug(
                "Jira server type detected: %s (base_url=%s)",
                "Server/DC" if self._is_server_cache else "Cloud",
                self.base_url,
            )
        return self._is_server_cache

    def _detect_server_type(self) -> bool:
        """
        Detect server type based on URL patterns.

        Detection logic:
        - Jira Cloud always uses *.atlassian.net domains
        - Everything else (custom domains, IP addresses) is Server/DC

        Returns:
            True if Server/DC, False if Cloud
        """
        if not self.base_url:
            return False

        # Jira Cloud uses *.atlassian.net domains
        if ".atlassian.net" in self.base_url.lower():
            return False

        # Everything else is likely Server/DC (including custom domains)
        return True

    def get_api_versions(self, endpoint_type: str = "default") -> Tuple[Union[int, str], ...]:
        """
        Get API versions to try for the given endpoint type.

        Different endpoint types have different version fallback strategies:
        - 'default': Standard endpoints (projects, issues, worklogs)
        - 'validation': Validation endpoints (/myself, /serverInfo)
        - 'discovery': Base URL discovery (/serverInfo)

        Args:
            endpoint_type: Type of endpoint ('default', 'validation', 'discovery')

        Returns:
            Tuple of API versions to try in order of preference

        Examples:
            >>> resolver = JiraApiVersionResolver("https://company.atlassian.net")
            >>> resolver.get_api_versions('default')
            (3, 2)  # Cloud: Try v3 first, fall back to v2

            >>> resolver = JiraApiVersionResolver("https://jira.company.com")
            >>> resolver.get_api_versions('default')
            (2,)  # Server/DC: Only v2 available
        """
        is_server_dc = self.is_server()

        if endpoint_type == "validation":
            # For validation, try all versions including 'latest'
            # Server/DC: v2, latest
            # Cloud: v3, v2, latest
            if is_server_dc:
                return (2, "latest")
            return (3, 2, "latest")

        elif endpoint_type == "discovery":
            # For discovery, prefer v2 (more stable)
            # Server/DC: v2 only
            # Cloud: v2, then v3
            return (2,) if is_server_dc else (2, 3)

        else:
            # Default: Standard REST API endpoints
            # Server/DC: v2 only (v3 doesn't exist)
            # Cloud: v3 first (latest features), fall back to v2
            return (2,) if is_server_dc else (3, 2)

    def get_server_type_name(self) -> str:
        """
        Get human-readable server type name.

        Returns:
            "Server/DC" or "Cloud"
        """
        return "Server/DC" if self.is_server() else "Cloud"

    def reset_cache(self) -> None:
        """
        Reset cached server type detection.

        Call this if the base_url changes or you want to force re-detection.
        """
        self._is_server_cache = None
        logger.debug("Jira server type cache reset")
