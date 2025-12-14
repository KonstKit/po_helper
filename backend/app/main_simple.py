from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config_simple import settings
from app.core.database_simple import create_tables, get_db, SessionLocal, Project, Task, User
from app.services.jira_service import jira_service
from typing import List, Dict, Any
import uvicorn

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables on startup
create_tables()


@app.get("/")
async def root():
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/api/v1/jira/connect")
async def connect_to_jira(
    base_url: str,
    email: str,
    api_token: str
):
    """Connect to Jira instance"""
    try:
        jira_service.connect(base_url, email, api_token)
        return {"status": "connected", "message": "Successfully connected to Jira"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/jira/projects/{project_key}")
async def get_jira_project(project_key: str):
    """Get project details from Jira"""
    try:
        project = jira_service.get_project(project_key)
        return project
    except Exception as e:
        return {"error": str(e), "mock_data": True, "project": {"key": project_key, "name": f"Mock Project {project_key}"}}


@app.get("/api/v1/jira/projects/{project_key}/issues")
async def get_project_issues(project_key: str, max_results: int = 100):
    """Get all issues for a project from Jira"""
    try:
        issues = jira_service.get_project_issues(project_key, max_results)
        return {
            "total": len(issues),
            "issues": issues
        }
    except Exception as e:
        # Return mock data
        mock_issues = [
            {
                "jira_id": "10001",
                "key": f"{project_key}-1",
                "summary": "Sample task 1",
                "status": "In Progress",
                "assignee_name": "John Doe",
                "estimate_hours": 8.0,
                "spent_hours": 4.0
            },
            {
                "jira_id": "10002",
                "key": f"{project_key}-2", 
                "summary": "Sample task 2",
                "status": "Todo",
                "assignee_name": "Jane Smith",
                "estimate_hours": 4.0,
                "spent_hours": 0.0
            }
        ]
        return {
            "total": len(mock_issues),
            "issues": mock_issues,
            "mock_data": True
        }


@app.get("/api/v1/projects/")
async def get_projects(db = Depends(get_db)):
    """Get all projects"""
    try:
        projects = db.query(Project).all()
        return projects
    except Exception as e:
        # Return mock data
        return [
            {
                "id": 1,
                "jira_key": "DEMO",
                "name": "Demo Project",
                "description": "This is a demo project",
                "status": "active"
            }
        ]


@app.get("/api/v1/analytics/demo")
async def get_demo_analytics():
    """Get demo analytics data"""
    return {
        "velocity": {
            "average_velocity": 22.5,
            "velocity_trend": "increasing"
        },
        "burndown": {
            "total_estimate": 100,
            "completed": 65,
            "remaining": 35
        },
        "risks": {
            "risk_level": "medium",
            "total_risks": 2,
            "risks": [
                {"type": "overdue_tasks", "count": 3, "severity": "medium"},
                {"type": "blocked_tasks", "count": 1, "severity": "high"}
            ]
        }
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)