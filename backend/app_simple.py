from flask import Flask, jsonify, request
from flask_cors import CORS
import json
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Simple in-memory data store
jira_config = {}
projects_data = []
tasks_data = []

@app.route('/')
def root():
    return jsonify({
        "message": "Welcome to PO Helper",
        "version": "1.0.0",
        "docs": "/docs"
    })

@app.route('/health')
def health_check():
    return jsonify({"status": "healthy"})

@app.route('/api/v1/jira/connect', methods=['POST'])
def connect_to_jira():
    """Connect to Jira instance"""
    try:
        data = request.json
        jira_config.update({
            'base_url': data.get('base_url'),
            'email': data.get('email'),
            'api_token': data.get('api_token')
        })
        return jsonify({"status": "connected", "message": "Successfully connected to Jira"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/v1/jira/projects/<project_key>')
def get_jira_project(project_key):
    """Get project details from Jira (mock data)"""
    return jsonify({
        "key": project_key,
        "name": f"Mock Project {project_key}",
        "description": f"This is a mock project for {project_key}",
        "lead": "Product Owner",
        "mock_data": True
    })

@app.route('/api/v1/jira/projects/<project_key>/issues')
def get_project_issues(project_key):
    """Get all issues for a project (mock data)"""
    mock_issues = [
        {
            "jira_id": "10001",
            "key": f"{project_key}-1",
            "summary": "Implement user authentication system",
            "description": "Create secure user login and registration",
            "task_type": "Story",
            "status": "In Progress",
            "priority": "High",
            "assignee_email": "john@example.com",
            "assignee_name": "John Doe",
            "estimate_hours": 16.0,
            "spent_hours": 8.0,
            "remaining_hours": 8.0,
            "created_date": datetime.now().isoformat(),
            "labels": ["authentication", "security"],
            "components": ["backend"],
            "is_blocker": False
        },
        {
            "jira_id": "10002",
            "key": f"{project_key}-2",
            "summary": "Design product catalog interface",
            "description": "Create responsive product listing page",
            "task_type": "Story",
            "status": "Todo",
            "priority": "Medium",
            "assignee_email": "jane@example.com",
            "assignee_name": "Jane Smith",
            "estimate_hours": 12.0,
            "spent_hours": 0.0,
            "remaining_hours": 12.0,
            "created_date": datetime.now().isoformat(),
            "labels": ["frontend", "ui"],
            "components": ["frontend"],
            "is_blocker": False
        },
        {
            "jira_id": "10003",
            "key": f"{project_key}-3",
            "summary": "Set up payment gateway integration",
            "description": "Integrate Stripe payment processing",
            "task_type": "Task",
            "status": "Review",
            "priority": "Critical",
            "assignee_email": "mike@example.com",
            "assignee_name": "Mike Wilson",
            "estimate_hours": 20.0,
            "spent_hours": 18.0,
            "remaining_hours": 2.0,
            "created_date": datetime.now().isoformat(),
            "labels": ["payment", "integration"],
            "components": ["backend"],
            "is_blocker": True
        },
        {
            "jira_id": "10004",
            "key": f"{project_key}-4",
            "summary": "Fix mobile responsive issues",
            "description": "Resolve layout problems on mobile devices",
            "task_type": "Bug",
            "status": "Done",
            "priority": "High",
            "assignee_email": "sarah@example.com",
            "assignee_name": "Sarah Connor",
            "estimate_hours": 8.0,
            "spent_hours": 10.0,
            "remaining_hours": 0.0,
            "created_date": datetime.now().isoformat(),
            "labels": ["mobile", "bugfix"],
            "components": ["frontend"],
            "is_blocker": False
        }
    ]
    
    return jsonify({
        "total": len(mock_issues),
        "issues": mock_issues,
        "mock_data": True
    })

@app.route('/api/v1/projects/')
def get_projects():
    """Get all projects"""
    mock_projects = [
        {
            "id": 1,
            "jira_key": "ECOM",
            "name": "E-commerce Platform",
            "description": "Main e-commerce application with user management and payments",
            "status": "active",
            "total_tasks": 45,
            "completed_tasks": 28,
            "completion_percentage": 62,
            "total_estimate_hours": 180,
            "total_spent_hours": 142
        },
        {
            "id": 2,
            "jira_key": "MOBILE",
            "name": "Mobile App",
            "description": "iOS and Android mobile application",
            "status": "active", 
            "total_tasks": 32,
            "completed_tasks": 18,
            "completion_percentage": 56,
            "total_estimate_hours": 120,
            "total_spent_hours": 85
        },
        {
            "id": 3,
            "jira_key": "DASH",
            "name": "Analytics Dashboard",
            "description": "Internal analytics and reporting dashboard",
            "status": "planning",
            "total_tasks": 24,
            "completed_tasks": 8,
            "completion_percentage": 33,
            "total_estimate_hours": 96,
            "total_spent_hours": 32
        }
    ]
    
    return jsonify(mock_projects)

@app.route('/api/v1/analytics/projects/<int:project_id>/velocity')
def get_project_velocity(project_id):
    """Get team velocity analytics"""
    return jsonify({
        "average_velocity": 22.5,
        "sprints_analyzed": 6,
        "velocity_trend": "increasing",
        "sprint_velocities": [
            {"sprint_name": "Sprint 1", "velocity": 18, "end_date": "2024-01-15"},
            {"sprint_name": "Sprint 2", "velocity": 22, "end_date": "2024-01-29"},
            {"sprint_name": "Sprint 3", "velocity": 20, "end_date": "2024-02-12"},
            {"sprint_name": "Sprint 4", "velocity": 24, "end_date": "2024-02-26"},
            {"sprint_name": "Sprint 5", "velocity": 26, "end_date": "2024-03-11"},
            {"sprint_name": "Sprint 6", "velocity": 25, "end_date": "2024-03-25"}
        ],
        "mock_data": True
    })

@app.route('/api/v1/analytics/projects/<int:project_id>/risks')
def identify_project_risks(project_id):
    """Identify and analyze project risks"""
    return jsonify({
        "risk_level": "medium",
        "risk_score": 6,
        "total_risks": 3,
        "risks": [
            {
                "type": "overdue_tasks",
                "severity": "high",
                "count": 3,
                "message": "3 tasks are overdue",
                "tasks": [
                    {"key": "PROJ-15", "summary": "Payment validation"},
                    {"key": "PROJ-23", "summary": "Security audit"},
                    {"key": "PROJ-31", "summary": "Performance optimization"}
                ]
            },
            {
                "type": "blocked_tasks", 
                "severity": "high",
                "count": 2,
                "message": "2 tasks are blocking other work",
                "tasks": [
                    {"key": "PROJ-12", "summary": "API authentication"},
                    {"key": "PROJ-18", "summary": "Database migration"}
                ]
            },
            {
                "type": "budget_overrun",
                "severity": "medium", 
                "count": 5,
                "message": "5 tasks exceeded estimates by 24.5 hours",
                "total_overrun_hours": 24.5
            }
        ],
        "mock_data": True
    })

@app.route('/api/v1/analytics/projects/<int:project_id>/forecast')
def forecast_completion(project_id):
    """Forecast project completion"""
    return jsonify({
        "forecast_available": True,
        "remaining_work_hours": 85,
        "average_velocity": 22.5,
        "sprints_needed": 3.8,
        "weeks_needed": 7.6,
        "estimated_completion_date": "2024-05-15",
        "confidence_level": "high",
        "mock_data": True
    })

@app.route('/api/v1/analytics/demo')
def get_demo_analytics():
    """Get demo analytics data"""
    return jsonify({
        "velocity": {
            "average_velocity": 22.5,
            "velocity_trend": "increasing",
            "sprint_success_rate": 78
        },
        "burndown": {
            "total_estimate": 180,
            "completed": 142,
            "remaining": 38,
            "completion_percentage": 79
        },
        "risks": {
            "risk_level": "medium",
            "total_risks": 3,
            "critical_risks": 0,
            "high_risks": 2,
            "medium_risks": 1
        },
        "team_performance": {
            "total_members": 5,
            "avg_tasks_per_member": 9,
            "efficiency_rating": 87
        },
        "mock_data": True
    })

if __name__ == '__main__':
    print("Starting PO Helper API server...")
    print("Visit http://localhost:8000 to access the API")
    print("API endpoints available at /api/v1/...")
    app.run(host='0.0.0.0', port=8000, debug=True)