from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from atlassian import Jira
from app.core.config import settings
from app.schemas.task import TaskCreate
from app.schemas.project import ProjectCreate

logger = logging.getLogger(__name__)


class JiraService:
    def __init__(self):
        self.client = None
        if settings.JIRA_BASE_URL and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN:
            self.connect()
    
    def connect(self, base_url: str = None, email: str = None, api_token: str = None):
        """Initialize connection to Jira"""
        try:
            self.client = Jira(
                url=base_url or settings.JIRA_BASE_URL,
                username=email or settings.JIRA_EMAIL,
                password=api_token or settings.JIRA_API_TOKEN,
                cloud=True
            )
            logger.info("Successfully connected to Jira")
        except Exception as e:
            logger.error(f"Failed to connect to Jira: {str(e)}")
            raise
    
    def get_project(self, project_key: str) -> Dict[str, Any]:
        """Get project details from Jira"""
        if not self.client:
            raise Exception("Jira client not initialized")
        
        try:
            project = self.client.project(project_key)
            return {
                "key": project["key"],
                "name": project["name"],
                "description": project.get("description", ""),
                "lead": project.get("lead", {}).get("displayName", ""),
                "url": project.get("self", "")
            }
        except Exception as e:
            logger.error(f"Failed to get project {project_key}: {str(e)}")
            raise
    
    def get_project_issues(self, project_key: str, max_results: int = 1000) -> List[Dict[str, Any]]:
        """Get all issues for a project"""
        if not self.client:
            raise Exception("Jira client not initialized")
        
        jql = f"project = {project_key} ORDER BY created DESC"
        issues = []
        start_at = 0
        
        while True:
            try:
                response = self.client.jql(
                    jql,
                    start=start_at,
                    limit=max_results,
                    expand="changelog"
                )
                
                batch_issues = response.get("issues", [])
                issues.extend(batch_issues)
                
                total = response.get("total", 0)
                if start_at + len(batch_issues) >= total:
                    break
                
                start_at += max_results
                
            except Exception as e:
                logger.error(f"Failed to get issues for project {project_key}: {str(e)}")
                raise
        
        return self._process_issues(issues)
    
    def get_sprint_issues(self, sprint_id: int) -> List[Dict[str, Any]]:
        """Get all issues in a sprint"""
        if not self.client:
            raise Exception("Jira client not initialized")
        
        jql = f"sprint = {sprint_id}"
        
        try:
            response = self.client.jql(jql, expand="changelog")
            issues = response.get("issues", [])
            return self._process_issues(issues)
        except Exception as e:
            logger.error(f"Failed to get issues for sprint {sprint_id}: {str(e)}")
            raise
    
    def get_active_sprints(self, board_id: int) -> List[Dict[str, Any]]:
        """Get active sprints for a board"""
        if not self.client:
            raise Exception("Jira client not initialized")
        
        try:
            sprints = self.client.get_all_sprints_from_board(board_id, state="active")
            return [self._process_sprint(sprint) for sprint in sprints]
        except Exception as e:
            logger.error(f"Failed to get active sprints for board {board_id}: {str(e)}")
            raise
    
    def _process_issues(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw Jira issues into our format"""
        processed_issues = []
        
        for issue in issues:
            fields = issue.get("fields", {})
            processed = {
                "jira_id": issue["id"],
                "key": issue["key"],
                "summary": fields.get("summary", ""),
                "description": fields.get("description", ""),
                "task_type": fields.get("issuetype", {}).get("name", ""),
                "status": fields.get("status", {}).get("name", ""),
                "priority": fields.get("priority", {}).get("name") if fields.get("priority") else None,
                "assignee_email": fields.get("assignee", {}).get("emailAddress") if fields.get("assignee") else None,
                "assignee_name": fields.get("assignee", {}).get("displayName") if fields.get("assignee") else None,
                "reporter_email": fields.get("reporter", {}).get("emailAddress") if fields.get("reporter") else None,
                "reporter_name": fields.get("reporter", {}).get("displayName") if fields.get("reporter") else None,
                "estimate_hours": self._seconds_to_hours(fields.get("timeoriginalestimate")),
                "spent_hours": self._seconds_to_hours(fields.get("timespent")),
                "remaining_hours": self._seconds_to_hours(fields.get("timeestimate")),
                "created_date": self._parse_date(fields.get("created")),
                "updated_date": self._parse_date(fields.get("updated")),
                "resolved_date": self._parse_date(fields.get("resolutiondate")),
                "due_date": self._parse_date(fields.get("duedate")),
                "labels": fields.get("labels", []),
                "components": [c.get("name") for c in fields.get("components", [])],
                "is_blocker": fields.get("priority", {}).get("name") == "Blocker" if fields.get("priority") else False,
                "sprint_id": self._get_sprint_id(fields),
                "story_points": fields.get("customfield_10026"),  # Common story points field
            }
            
            # Get blocked/blocking issues
            issue_links = fields.get("issuelinks", [])
            processed["blocked_by"] = []
            processed["blocks"] = []
            
            for link in issue_links:
                link_type = link.get("type", {}).get("name", "")
                if "blocks" in link_type.lower():
                    if "inwardIssue" in link:
                        processed["blocked_by"].append(link["inwardIssue"]["key"])
                    if "outwardIssue" in link:
                        processed["blocks"].append(link["outwardIssue"]["key"])
            
            processed_issues.append(processed)
        
        return processed_issues
    
    def _process_sprint(self, sprint: Dict[str, Any]) -> Dict[str, Any]:
        """Process raw Jira sprint into our format"""
        return {
            "jira_id": str(sprint.get("id")),
            "name": sprint.get("name", ""),
            "state": sprint.get("state", ""),
            "start_date": self._parse_date(sprint.get("startDate")),
            "end_date": self._parse_date(sprint.get("endDate")),
            "complete_date": self._parse_date(sprint.get("completeDate")),
            "goal": sprint.get("goal", "")
        }
    
    def _seconds_to_hours(self, seconds: Optional[int]) -> Optional[float]:
        """Convert seconds to hours"""
        if seconds is None:
            return None
        return round(seconds / 3600, 2)
    
    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse Jira date string to datetime"""
        if not date_str:
            return None
        try:
            # Jira dates are in ISO format
            if "T" in date_str:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return datetime.fromisoformat(date_str)
        except:
            return None
    
    def _get_sprint_id(self, fields: Dict[str, Any]) -> Optional[str]:
        """Extract sprint ID from custom fields"""
        # Sprint field is usually customfield_10020 or similar
        sprint_field = fields.get("customfield_10020") or fields.get("sprint")
        if sprint_field and isinstance(sprint_field, list) and len(sprint_field) > 0:
            # Sprint field contains sprint objects
            sprint = sprint_field[0]
            if isinstance(sprint, dict):
                return str(sprint.get("id"))
            elif isinstance(sprint, str) and "id=" in sprint:
                # Parse sprint string like "com.atlassian.greenhopper.service.sprint.Sprint@1234[id=123,...]"
                import re
                match = re.search(r'id=(\d+)', sprint)
                if match:
                    return match.group(1)
        return None
    
    def get_worklogs(self, issue_key: str) -> List[Dict[str, Any]]:
        """Get worklogs for an issue"""
        if not self.client:
            raise Exception("Jira client not initialized")
        
        try:
            worklogs = self.client.issue_worklog(issue_key)
            processed_logs = []
            
            for log in worklogs:
                processed_logs.append({
                    "jira_id": log.get("id"),
                    "author_email": log.get("author", {}).get("emailAddress"),
                    "author_name": log.get("author", {}).get("displayName"),
                    "time_spent_seconds": log.get("timeSpentSeconds"),
                    "comment": log.get("comment", ""),
                    "started": self._parse_date(log.get("started")),
                    "created": self._parse_date(log.get("created")),
                    "updated": self._parse_date(log.get("updated"))
                })
            
            return processed_logs
        except Exception as e:
            logger.error(f"Failed to get worklogs for issue {issue_key}: {str(e)}")
            raise


jira_service = JiraService()