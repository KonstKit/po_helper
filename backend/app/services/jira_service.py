"""
Jira Service - Backward Compatibility Layer.

This module provides backward compatibility by importing from the refactored
jira package and creating a global jira_service instance.

The JiraService class and all business logic have been extracted to:
    backend/app/services/jira/

This file now serves as a simple entry point that:
1. Imports JiraService from the jira package
2. Imports exceptions (JiraAuthError, JiraUnexpectedResponse)
3. Creates the global jira_service instance

Usage:
    from app.services.jira_service import jira_service

    # Use the global instance
    project = jira_service.get_project("PROJ")
    issues = jira_service.get_project_issues("PROJ")

All business logic has been moved to specialized services in the jira/ package.
"""

# Import from refactored jira package
from app.services.jira import (
    JiraService,
    JiraAuthError,
    JiraUnexpectedResponse,
)
from app.core.metrics import metrics

# Create global instance for backward compatibility
jira_service = JiraService()

# Export for easy importing
__all__ = [
    "JiraService",
    "JiraAuthError",
    "JiraUnexpectedResponse",
    "jira_service",
    "metrics",
]
