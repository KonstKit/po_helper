from fastapi import APIRouter
from app.api.api_v1.endpoints import (
    auth,
    users,
    roles,
    projects,
    tasks,
    jira,
    analytics,
    settings,
    confluence,
    traceability,
    health,
    git_router,
    quality,
    testing,
    jira_fields,
    tasks_async,
    project_repository,
    gitlab_projects,
    capacity,
    testrail,
    usage_analytics,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(jira.router, prefix="/jira", tags=["jira"])
api_router.include_router(jira_fields.router, prefix="/jira-fields", tags=["jira-fields"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(confluence.router, prefix="/confluence", tags=["confluence"])
api_router.include_router(traceability.router, prefix="/traceability", tags=["traceability"])
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(git_router.router, prefix="/git", tags=["git"])
api_router.include_router(project_repository.router, prefix="", tags=["project-repository"])
api_router.include_router(gitlab_projects.router, prefix="", tags=["gitlab"])
api_router.include_router(quality.router, prefix="/quality", tags=["quality"])
api_router.include_router(testing.router, prefix="/testing", tags=["testing"])
api_router.include_router(tasks_async.router, prefix="/async-tasks", tags=["async-tasks"])
api_router.include_router(capacity.router, prefix="/capacity", tags=["capacity"])
api_router.include_router(testrail.router, prefix="/testrail", tags=["testrail"])
api_router.include_router(usage_analytics.router, prefix="/usage-analytics", tags=["usage-analytics"])
