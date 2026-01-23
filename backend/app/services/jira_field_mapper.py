"""
Jira Field Mapper Service
Provides universal field mapping and discovery for different Jira configurations
"""

import asyncio
import re
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum

from app.services.jira.contracts import IJiraTransport

logger = logging.getLogger(__name__)


class FieldType(Enum):
    """Standard field types we need to map"""

    SPRINT = "sprint"
    EPIC_LINK = "epic_link"
    STORY_POINTS = "story_points"
    BUSINESS_VALUE = "business_value"
    TEAM = "team"
    COMPONENTS = "components"
    FIX_VERSION = "fix_version"
    REPORTER = "reporter"
    TIME_ORIGINAL_ESTIMATE = "time_original_estimate"
    TIME_SPENT = "time_spent"
    TIME_REMAINING = "time_remaining"
    AGGREGATE_TIME_ORIGINAL = "aggregate_time_original"
    AGGREGATE_TIME_SPENT = "aggregate_time_spent"
    AGGREGATE_TIME_REMAINING = "aggregate_time_remaining"


class DiscoveryStrategy(Enum):
    """Methods for discovering field mappings"""

    AUTO = "auto"
    CUSTOM_FIELD = "custom_field"
    AGILE_API = "agile_api"
    BOARD_API = "board_api"
    JQL = "jql"
    MANUAL = "manual"


class JiraFieldMapper:
    """Universal field mapper for Jira integrations"""

    def __init__(self, transport: Optional[IJiraTransport], base_url: Optional[str] = None):
        self.transport = transport
        self.base_url = base_url or getattr(transport, "base_url", None)
        self.field_cache: Dict[str, Dict[str, Any]] = {}  # field_id -> field_info
        self.mappings: Dict[FieldType, str] = {}  # FieldType -> field_id
        self.last_discovery: Optional[datetime] = None
        self.cache_ttl = timedelta(hours=24)

    def set_transport(
        self, transport: Optional[IJiraTransport], base_url: Optional[str] = None
    ) -> None:
        """Update Jira transport and base URL."""
        self.transport = transport
        self.base_url = base_url or getattr(transport, "base_url", None)

    def _client(self) -> IJiraTransport:
        """Return initialized Jira transport or raise if not connected."""
        if not self.transport:
            raise Exception("Jira transport not configured")
        return self.transport

    async def _request_json(self, endpoint: str, **kwargs) -> Any:
        """Run a Jira HTTP request off the event loop and parse JSON."""
        client = self._client()

        def _do_request() -> Any:
            headers = kwargs.pop("headers", None) or client.headers()
            response = client.get(endpoint, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()

        return await asyncio.to_thread(_do_request)

    async def discover_fields(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Discover all available fields from Jira
        Returns mapping of field IDs to field information
        """
        # Check cache
        if not force_refresh and self.last_discovery is not None:
            if datetime.utcnow() - self.last_discovery < self.cache_ttl:
                logger.info("Using cached field discovery")
                return self.field_cache

        try:
            # Get all fields from Jira API
            fields = await self._fetch_all_fields()

            # Build cache
            self.field_cache = {}
            for field in fields:
                field_id = field.get("id", field.get("key"))
                if field_id:
                    self.field_cache[field_id] = {
                        "id": field_id,
                        "name": field.get("name", ""),
                        "type": field.get("schema", {}).get("type")
                        if isinstance(field.get("schema"), dict)
                        else None,
                        "custom": field.get("custom", field_id.startswith("customfield_")),
                        "schema": field.get("schema"),
                        "key": field.get("key"),
                    }

            self.last_discovery = datetime.utcnow()
            logger.info(f"Discovered {len(self.field_cache)} fields from Jira")

            # Auto-map common fields
            await self._auto_map_fields()

            return self.field_cache

        except Exception as e:
            logger.error(f"Field discovery failed: {e}")
            return {}

    async def _fetch_all_fields(self) -> List[Dict]:
        """Fetch all fields from Jira API"""
        if not self.base_url:
            return []

        # Try v3 then v2
        for version in [3, 2]:
            try:
                endpoint = f"/rest/api/{version}/field"
                data = await self._request_json(endpoint)
                return data or []
            except Exception as e:
                logger.warning(f"Failed to fetch fields from v{version}: {e}")
                continue

        return []

    async def _auto_map_fields(self):
        """Automatically map fields based on patterns"""
        pattern_mappings = {
            FieldType.SPRINT: [r"sprint", r"iteration", r"cycle"],
            FieldType.EPIC_LINK: [r"epic\s*link", r"epic", r"parent\s*link"],
            FieldType.STORY_POINTS: [r"story\s*point", r"point", r"estimate.*point", r"size"],
            FieldType.BUSINESS_VALUE: [r"business\s*value", r"value", r"benefit", r"roi"],
            FieldType.TEAM: [r"team", r"squad", r"group"],
            FieldType.FIX_VERSION: [r"fix.*version", r"release", r"version"],
        }

        for field_type, patterns in pattern_mappings.items():
            if field_type in self.mappings:
                continue  # Skip if already mapped

            for field_id, field_info in self.field_cache.items():
                field_name = field_info.get("name", "").lower()

                for pattern in patterns:
                    if re.search(pattern, field_name, re.IGNORECASE):
                        self.mappings[field_type] = field_id
                        logger.info(
                            f"Auto-mapped {field_type.value} to {field_id} ({field_info['name']})"
                        )
                        break

                if field_type in self.mappings:
                    break

    def get_field_id(self, field_type: FieldType) -> Optional[str]:
        """Get the Jira field ID for a given field type"""
        return self.mappings.get(field_type)

    def set_field_mapping(self, field_type: FieldType, field_id: str):
        """Manually set a field mapping"""
        self.mappings[field_type] = field_id
        logger.info(f"Manually mapped {field_type.value} to {field_id}")

    async def parse_sprint_field(self, field_value: Any) -> List[Dict[str, Any]]:
        """
        Parse sprint data from various formats
        Handles multiple Jira sprint field formats
        """
        if not field_value:
            return []

        sprints = []

        # Format 1: List of sprint objects
        if isinstance(field_value, list):
            for item in field_value:
                sprint = self._parse_single_sprint(item)
                if sprint:
                    sprints.append(sprint)

        # Format 2: Single sprint object
        elif isinstance(field_value, dict):
            sprint = self._parse_single_sprint(field_value)
            if sprint:
                sprints.append(sprint)

        # Format 3: String representation
        elif isinstance(field_value, str):
            # Try to parse Jira's string format
            sprint = self._parse_sprint_string(field_value)
            if sprint:
                sprints.append(sprint)

        return sprints

    def _parse_single_sprint(self, sprint_data: Any) -> Optional[Dict[str, Any]]:
        """Parse a single sprint from various formats"""

        # Standard object format
        if isinstance(sprint_data, dict):
            return {
                "id": sprint_data.get("id"),
                "name": sprint_data.get("name"),
                "state": sprint_data.get("state"),
                "startDate": sprint_data.get("startDate"),
                "endDate": sprint_data.get("endDate"),
                "completeDate": sprint_data.get("completeDate"),
                "goal": sprint_data.get("goal"),
            }

        # String format like "com.atlassian.greenhopper.service.sprint.Sprint@xxx[id=123,name=Sprint 1,...]"
        elif isinstance(sprint_data, str):
            return self._parse_sprint_string(sprint_data)

        return None

    def _parse_sprint_string(self, sprint_str: str) -> Optional[Dict[str, Any]]:
        """Parse Jira's sprint string representation"""
        sprint = {}

        # Extract ID
        id_match = re.search(r"id=(\d+)", sprint_str)
        if id_match:
            sprint["id"] = id_match.group(1)

        # Extract name
        name_match = re.search(r"name=([^,\]]+)", sprint_str)
        if name_match:
            sprint["name"] = name_match.group(1)

        # Extract state
        state_match = re.search(r"state=([^,\]]+)", sprint_str)
        if state_match:
            sprint["state"] = state_match.group(1)

        # Extract dates
        start_match = re.search(r"startDate=([^,\]]+)", sprint_str)
        if start_match and start_match.group(1) != "<null>":
            sprint["startDate"] = start_match.group(1)

        end_match = re.search(r"endDate=([^,\]]+)", sprint_str)
        if end_match and end_match.group(1) != "<null>":
            sprint["endDate"] = end_match.group(1)

        complete_match = re.search(r"completeDate=([^,\]]+)", sprint_str)
        if complete_match and complete_match.group(1) != "<null>":
            sprint["completeDate"] = complete_match.group(1)

        return sprint if sprint else None

    async def get_issue_with_mapped_fields(self, issue_key: str) -> Dict[str, Any]:
        """
        Get issue with fields mapped to standard names
        Uses discovered field mappings
        """
        # Ensure fields are discovered
        if not self.field_cache:
            await self.discover_fields()

        # Get issue from Jira
        issue_data = await self._fetch_issue_with_all_fields(issue_key)
        if not issue_data:
            return {}

        fields = issue_data.get("fields", {})

        # Map fields to standard names
        mapped_issue = {
            "key": issue_data.get("key"),
            "id": issue_data.get("id"),
            "summary": fields.get("summary"),
            "description": fields.get("description"),
            "status": self._get_nested(fields, "status", "name"),
            "priority": self._get_nested(fields, "priority", "name"),
            "assignee": self._get_user_info(fields.get("assignee")),
            "reporter": self._get_user_info(fields.get("reporter")),
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "resolved": fields.get("resolutiondate"),
            "duedate": fields.get("duedate"),
            "labels": fields.get("labels", []),
            "components": [c.get("name") for c in fields.get("components", [])],
            "issueType": self._get_nested(fields, "issuetype", "name"),
        }

        # Add custom mapped fields
        for field_type in FieldType:
            field_id = self.get_field_id(field_type)
            if field_id and field_id in fields:
                field_value = fields[field_id]

                # Special handling for sprints
                if field_type == FieldType.SPRINT:
                    mapped_issue["sprints"] = await self.parse_sprint_field(field_value)
                else:
                    mapped_issue[field_type.value] = field_value

        # Time tracking fields (standard fields)
        timetracking = fields.get("timetracking", {})
        if timetracking:
            mapped_issue["timeOriginalEstimate"] = timetracking.get("originalEstimateSeconds")
            mapped_issue["timeSpent"] = timetracking.get("timeSpentSeconds")
            mapped_issue["timeRemaining"] = timetracking.get("remainingEstimateSeconds")

        # Aggregate time fields (if available)
        mapped_issue["aggregateTimeOriginalEstimate"] = fields.get("aggregatetimeoriginalestimate")
        mapped_issue["aggregateTimeSpent"] = fields.get("aggregatetimespent")
        mapped_issue["aggregateTimeEstimate"] = fields.get("aggregatetimeestimate")

        return mapped_issue

    async def _fetch_issue_with_all_fields(self, issue_key: str) -> Optional[Dict]:
        """Fetch issue with all available fields"""
        if not self.base_url:
            return None

        for version in [3, 2]:
            try:
                endpoint = f"/rest/api/{version}/issue/{issue_key}"
                params = {"expand": "names,schema"}
                return await self._request_json(endpoint, params=params)
            except Exception as e:
                logger.warning(f"Failed to fetch issue {issue_key} from v{version}: {e}")
                continue

        return None

    async def _fetch_project_issues(
        self,
        project_key: str,
        max_results: int,
    ) -> List[Dict[str, Any]]:
        """Fetch sample issues for a project (used for calibration)."""
        if not self.base_url:
            return []

        max_results = max(1, min(int(max_results or 10), 100))

        for version in [3, 2]:
            try:
                endpoint = f"/rest/api/{version}/search"
                params = {
                    "jql": f'project="{project_key}"',
                    "maxResults": max_results,
                    "startAt": 0,
                    "fields": "*all",
                }
                data = await self._request_json(endpoint, params=params)
                issues = data.get("issues") if isinstance(data, dict) else None
                return issues or []
            except Exception as e:
                logger.warning(f"Failed to fetch issues for {project_key} from v{version}: {e}")
                continue

        return []

    def _get_nested(self, data: dict, *keys: str) -> Any:
        """Safely get nested dictionary values"""
        current: Any = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None
        return current

    def _get_user_info(self, user_data: Optional[Dict]) -> Dict[str, str]:
        """Extract user information"""
        if not user_data:
            return {}

        return {
            "name": user_data.get("displayName", ""),
            "email": user_data.get("emailAddress", ""),
            "accountId": user_data.get("accountId", ""),
            "key": user_data.get("key", ""),
        }

    async def calibrate(
        self, sample_project_key: str, sample_size: int = 10
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calibrate field mappings by analyzing sample issues
        Returns confidence scores for each mapping
        """
        logger.info(f"Starting calibration with project {sample_project_key}")

        # Get sample issues
        issues = await self._fetch_project_issues(sample_project_key, sample_size)
        if not issues:
            logger.warning(
                "No issues found for calibration; falling back to name-based auto mapping"
            )
            # Fallback path: rely on field discovery + name patterns
            try:
                await self.discover_fields(force_refresh=False)
            except Exception:
                pass
            # self._auto_map_fields() is called inside discover_fields, but ensure mappings exist
            if self.mappings:
                # Build a synthetic calibration result from name-based mapping
                fallback: Dict[str, Dict[str, Any]] = {}
                for ft, fid in self.mappings.items():
                    if not fid:
                        continue
                    try:
                        fallback[fid] = {
                            "type": ft.value,
                            "confidence": 0.6,  # heuristic confidence for name-based mapping
                        }
                    except Exception:
                        continue
                return fallback
            return {}

        # Analyze fields
        field_analysis: Dict[str, Dict[str, Any]] = {}

        for issue in issues:
            fields = issue.get("fields", {}) if "fields" in issue else issue

            for field_id, value in fields.items():
                if not field_id.startswith("customfield_"):
                    continue

                if field_id not in field_analysis:
                    field_analysis[field_id] = {
                        "samples": [],
                        "non_null_count": 0,
                        "detected_type": None,
                    }

                if value is not None:
                    field_analysis[field_id]["non_null_count"] += 1
                    field_analysis[field_id]["samples"].append(value)

        # Determine field types based on samples
        calibration_results: Dict[str, Dict[str, Any]] = {}

        for field_id, analysis in field_analysis.items():
            if analysis["non_null_count"] == 0:
                continue

            confidence = analysis["non_null_count"] / len(issues)
            samples = analysis["samples"]

            # Check for sprint pattern
            if self._looks_like_sprint(samples):
                calibration_results[field_id] = {
                    "type": FieldType.SPRINT.value,
                    "confidence": confidence,
                }
                if confidence > 0.5:  # Auto-map if confident
                    self.set_field_mapping(FieldType.SPRINT, field_id)

            # Check for story points pattern
            elif self._looks_like_story_points(samples):
                calibration_results[field_id] = {
                    "type": FieldType.STORY_POINTS.value,
                    "confidence": confidence,
                }
                if confidence > 0.5:
                    self.set_field_mapping(FieldType.STORY_POINTS, field_id)

            # Check for epic link pattern
            elif self._looks_like_epic_link(samples):
                calibration_results[field_id] = {
                    "type": FieldType.EPIC_LINK.value,
                    "confidence": confidence,
                }
                if confidence > 0.5:
                    self.set_field_mapping(FieldType.EPIC_LINK, field_id)

        logger.info(f"Calibration complete. Found {len(calibration_results)} potential mappings")
        return calibration_results

    def _looks_like_sprint(self, samples: List[Any]) -> bool:
        """Detect if samples look like sprint data"""
        for sample in samples:
            if isinstance(sample, list) and sample:
                first = sample[0]
                # Check for sprint-like structure
                if isinstance(first, dict) and any(k in first for k in ["id", "name", "state"]):
                    if "sprint" in str(first).lower():
                        return True
                elif isinstance(first, str) and ("sprint" in first.lower() or "id=" in first):
                    return True
            elif isinstance(sample, str) and ("sprint" in sample.lower() or "id=" in sample):
                return True
        return False

    def _looks_like_story_points(self, samples: List[Any]) -> bool:
        """Detect if samples look like story points"""
        numeric_count = 0
        for sample in samples:
            if isinstance(sample, (int, float)) and 0 <= sample <= 100:
                numeric_count += 1
        return numeric_count > len(samples) * 0.7

    def _looks_like_epic_link(self, samples: List[Any]) -> bool:
        """Detect if samples look like epic links"""
        for sample in samples:
            if isinstance(sample, str) and re.match(r"^[A-Z]+-\d+$", sample):
                return True
        return False

    async def get_sprints_with_fallback(self, issue_key: str) -> List[Dict[str, Any]]:
        """
        Get sprints for an issue using multiple strategies
        Returns sprints from the first successful strategy
        """
        strategies = [
            self._get_sprints_from_custom_field,
            self._get_sprints_from_agile_api,
            self._get_sprints_from_board_api,
        ]

        for strategy in strategies:
            try:
                sprints = await strategy(issue_key)
                if sprints:
                    logger.info(f"Got sprints for {issue_key} using {strategy.__name__}")
                    return sprints
            except Exception as e:
                logger.debug(f"Strategy {strategy.__name__} failed for {issue_key}: {e}")
                continue

        logger.warning(f"No sprints found for {issue_key} using any strategy")
        return []

    async def _get_sprints_from_custom_field(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get sprints from custom field"""
        sprint_field = self.get_field_id(FieldType.SPRINT)
        if not sprint_field:
            return []

        issue = await self._fetch_issue_with_all_fields(issue_key)
        if not issue:
            return []

        field_value = issue.get("fields", {}).get(sprint_field)
        return await self.parse_sprint_field(field_value)

    async def _get_sprints_from_agile_api(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get sprints from Agile API"""
        if not self.base_url:
            return []

        try:
            endpoint = f"/rest/agile/1.0/issue/{issue_key}"
            data = await self._request_json(endpoint)

            sprint_field = data.get("fields", {}).get("sprint")
            if sprint_field:
                return await self.parse_sprint_field(sprint_field)

            # Also check for sprints array
            sprints = data.get("fields", {}).get("sprints", [])
            return sprints if isinstance(sprints, list) else []

        except Exception as e:
            logger.debug(f"Agile API failed for {issue_key}: {e}")
            return []

    async def _get_sprints_from_board_api(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get sprints by finding issue in board sprints"""
        # This is more complex and requires knowing the board ID
        # Implementing as fallback only
        return []

    def export_configuration(self) -> Dict[str, Any]:
        """Export current field mappings for reuse"""
        return {
            "mappings": {k.value: v for k, v in self.mappings.items()},
            "jira_url": self.base_url,
            "discovered_fields": len(self.field_cache),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def import_configuration(self, config: Dict[str, Any]):
        """Import field mappings from configuration"""
        mappings = config.get("mappings", {})
        for field_type_str, field_id in mappings.items():
            try:
                field_type = FieldType(field_type_str)
                self.set_field_mapping(field_type, field_id)
            except ValueError:
                logger.warning(f"Unknown field type in import: {field_type_str}")

        logger.info(f"Imported {len(mappings)} field mappings")
