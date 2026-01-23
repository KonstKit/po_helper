"""Git integration module for handling webhooks, metrics, and CI/CD."""

from .webhooks import handle_github_webhook, handle_gitlab_webhook
from .metrics import calculate_pr_metrics, get_pr_list, get_commits_for_issue
from .ci import process_ci_results

__all__ = [
    "handle_github_webhook",
    "handle_gitlab_webhook",
    "calculate_pr_metrics",
    "get_pr_list",
    "get_commits_for_issue",
    "process_ci_results",
]
