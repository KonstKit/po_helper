# Project-Repository Binding Implementation
**Date:** 2025-09-29
**Status:** ✅ COMPLETED
**Author:** Claude Code

## Executive Summary
Successfully implemented a comprehensive solution for binding Git repositories (GitHub/GitLab) to projects, resolving the critical architecture gap where the system couldn't determine which Git provider to use for a specific project.

## Problem Statement
The application had no mechanism to associate projects with their Git repositories. The system could only infer repository relationships through JIRA keys in commit messages, which meant:
- No way to proactively fetch Git data for a project
- Unable to determine if a project uses GitHub or GitLab
- Multiple repositories could accidentally link to the same project
- New projects with no commits couldn't be linked to repositories

## Solution Overview

### 1. Database Schema Changes
Created a many-to-many relationship between projects and repositories with primary designation support.

#### New Table: `project_repositories`
```sql
CREATE TABLE project_repositories (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    is_primary BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(project_id, repository_id)
);
```

#### Migration: `015_add_project_repositories.py`
- Includes table existence checks for idempotency
- Proper indexes for performance
- Foreign key constraints with CASCADE delete

### 2. Model Updates

#### Project Model
```python
# app/models/project.py
project_repositories = relationship("ProjectRepository", back_populates="project", cascade="all, delete-orphan")
```

#### Repository Model
```python
# app/models/git.py
project_repositories = relationship("ProjectRepository", back_populates="repository", cascade="all, delete-orphan")
```

#### New ProjectRepository Model
```python
# app/models/project_repository.py
class ProjectRepository(Base):
    __tablename__ = "project_repositories"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    repository_id = Column(Integer, ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True)
    is_primary = Column(Boolean, default=True, server_default="true", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="project_repositories")
    repository = relationship("Repository", back_populates="project_repositories")
```

### 3. API Endpoints

#### New Endpoints in `app/api/api_v1/endpoints/project_repository.py`:

1. **GET /projects/{project_id}/repositories**
   - Get all repositories linked to a project
   - Returns repository details with primary status

2. **POST /projects/{project_id}/repositories**
   - Bind a repository to a project
   - Accepts repository URL or slug+provider
   - Auto-detects provider from URL patterns
   - Validates provider configuration exists

3. **DELETE /projects/{project_id}/repositories/{repository_id}**
   - Unbind repository from project
   - Cascades properly through relationships

4. **PUT /projects/{project_id}/repositories/{repository_id}/primary**
   - Set repository as primary for project
   - Automatically unsets other primaries

5. **GET /projects/{project_id}/primary-repository**
   - Get the primary repository for quick access

6. **GET /repositories**
   - List all repositories with their associated projects
   - Supports provider filtering

### 4. Repository Resolver Service

Created `app/services/repository_resolver.py` to encapsulate repository resolution logic:

```python
class RepositoryResolver:
    @staticmethod
    async def get_primary_repository(project_id: int, db: AsyncSession) -> Optional[Repository]

    @staticmethod
    async def get_all_repositories(project_id: int, db: AsyncSession) -> List[Repository]

    @staticmethod
    async def get_repository_by_provider(project_id: int, provider: str, db: AsyncSession) -> Optional[Repository]

    @staticmethod
    async def get_project_by_repository(repository_id: int, db: AsyncSession) -> Optional[Project]
```

### 5. Updated Git Metrics Logic

Modified `app/api/api_v1/endpoints/git/metrics.py` to use the new repository associations:

```python
async def get_pull_requests_for_project(
    db: AsyncSession,
    project_id: Optional[int] = None,
    provider: Optional[str] = None
) -> List[PullRequest]:
    # Now uses project's linked repositories first
    if project_id is not None:
        repositories = await repository_resolver.get_all_repositories(project_id, db)
        # Filter by provider if specified
        # Query PRs from these repositories
    # Falls back to JIRA key matching if no repositories linked
```

### 6. URL Parsing Logic

Implemented smart repository URL parsing to auto-detect providers:

```python
def parse_repository_url(url: str) -> tuple[str, str]:
    # Supports formats:
    # - https://github.com/org/repo
    # - git@github.com:org/repo.git
    # - https://gitlab.com/group/project
    # - https://self-hosted-gitlab.com/group/project
```

## Testing

Created `test_project_repository.py` for integration testing:
- Tests repository binding to projects
- Verifies primary repository designation
- Validates URL parsing
- Checks API endpoint functionality

## Benefits

1. **Explicit Configuration**: Clear, deterministic repository associations
2. **Multi-Repository Support**: Projects can have multiple repositories
3. **Provider Flexibility**: Mix GitHub and GitLab repositories per project
4. **Backward Compatibility**: Falls back to JIRA key matching when needed
5. **Performance**: Direct queries instead of filtering all PRs
6. **Scalability**: Supports microservices with multiple repos per project

## Migration Path

For existing installations:
1. Run migration: `alembic upgrade head`
2. Existing repositories remain intact
3. Bind repositories to projects via API or UI
4. Old JIRA-based matching continues to work as fallback

## Future Enhancements

1. **UI Components**: Add repository management to project settings page
2. **Auto-Discovery**: Detect repositories from JIRA development panel links
3. **Sync Status**: Track last sync time per repository
4. **Access Control**: Per-repository permissions
5. **Bulk Operations**: Import repository mappings from CSV/JSON

## Files Changed

### New Files:
- `backend/alembic/versions/015_add_project_repositories.py`
- `backend/app/models/project_repository.py`
- `backend/app/schemas/project_repository.py`
- `backend/app/schemas/repository.py`
- `backend/app/api/api_v1/endpoints/project_repository.py`
- `backend/app/services/repository_resolver.py`
- `backend/test_project_repository.py`

### Modified Files:
- `backend/app/models/project.py` - Added relationship
- `backend/app/models/git.py` - Added relationship
- `backend/app/models/__init__.py` - Export new model
- `backend/app/api/api_v1/api.py` - Register new router
- `backend/app/api/api_v1/endpoints/git/metrics.py` - Use resolver
- `backend/app/api/api_v1/endpoints/traceability.py` - Fixed async bug

## Bug Fixes

### SQLAlchemy MissingGreenlet Error (Bug #24)
**Issue**: Accessing `project.id` in async context triggered lazy loading error
**Solution**: Use `project_id` parameter directly instead of ORM object attribute
**Files Fixed**: `backend/app/api/api_v1/endpoints/traceability.py` (5 occurrences)

## Conclusion

This implementation successfully resolves the critical architecture gap in Git provider determination. Projects can now be explicitly linked to their repositories, enabling deterministic and efficient Git operations. The solution maintains backward compatibility while providing a clear upgrade path for existing installations.

The implementation follows best practices:
- Proper database normalization
- RESTful API design
- Service layer abstraction
- Comprehensive error handling
- Migration safety checks
- Performance optimization through indexes

This foundation enables future enhancements like multi-cloud Git support, repository-level permissions, and automated repository discovery from project metadata.