from __future__ import annotations

from typing import Dict, Any, List, Optional


class TestRailService:
    """Lightweight placeholder for TestRail integration.

    Real connections require URL, credentials, and TestRail API client.
    This skeleton defines interfaces used by the app without external calls.
    """

    def __init__(self, base_url: Optional[str] = None, user: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = base_url
        self.user = user
        self.api_key = api_key

    def sync_test_cases(self, project_id: str) -> List[Dict[str, Any]]:
        """Pull test cases from TestRail project and normalize.
        Currently returns empty list as a stub.
        """
        return []

    def create_test_run(self, milestone_id: str) -> Dict[str, Any]:
        """Create a test run for a milestone.
        Returns stub payload.
        """
        return {"created": True, "milestone_id": milestone_id}

    def import_results(self, run_id: str) -> Dict[str, Any]:
        """Fetch results for a run and normalize.
        Returns stub payload.
        """
        return {"run_id": run_id, "results": []}


testrail_service = TestRailService()

