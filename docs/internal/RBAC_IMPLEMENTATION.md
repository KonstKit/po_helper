# RBAC Implementation Documentation

**Version:** 1.0
**Date:** 2025-10-02
**Status:** ✅ COMPLETED

## Overview

Role-Based Access Control (RBAC) has been fully implemented in the PO Helper system. This provides fine-grained permission management for all API endpoints and resources.

## Implementation Summary

### ✅ Core RBAC Infrastructure

1. **Database Schema** (Migration `017_add_rbac_tables`)
   - `roles` table: Stores role definitions with permissions
   - `user_roles` table: Many-to-many association between users and roles
   - Foreign keys with CASCADE delete for data integrity
   - Backward compatibility with existing `is_superuser` flag

2. **Permission Model** (`app/models/rbac.py`)
   - Centralized `Permissions` class with all permission constants
   - Permission format: `"resource:action"` (e.g., `"project:create"`)
   - Special `admin` permission grants all access
   - 5 system roles: Admin, PO, Developer, QA, Viewer

3. **User Model Extensions** (`app/models/user.py`)
   - `has_permission(permission: str) -> bool` - Check if user has specific permission
   - `has_role(role_name: str) -> bool` - Check if user has specific role
   - `roles` relationship - Many-to-many with Role model
   - Superuser backward compatibility maintained

4. **Security Dependencies** (`app/api/deps.py`)
   - `require_permission(permission: str)` - FastAPI dependency for permission checking
   - `require_role(role_name: str)` - FastAPI dependency for role checking
   - Automatic 403 Forbidden response on permission denial
   - Logging of permission violations

### ✅ API Endpoints Protection

#### Projects (`/api/v1/projects`)
- `GET /` - Requires `project:view`
- `GET /{project_id}` - Requires `project:view`
- `POST /` - Requires `project:create`
- `PATCH /{project_id}` - Requires `project:update`
- `DELETE /{project_id}` - Requires `project:delete`
- `DELETE /{project_id}/purge` - Requires `project:delete`

#### Tasks (`/api/v1/tasks`)
- `GET /` - Requires `task:view`
- `GET /{task_id}` - Requires `task:view`
- `POST /` - Requires `task:create`
- `PATCH /{task_id}` - Requires `task:update`
- `DELETE /{task_id}` - Requires `task:delete`

#### Settings (`/api/v1/settings`)
- All GET endpoints - Require `settings:view`
- All PUT/POST endpoints - Require `settings:update`

#### Users (`/api/v1/users`)
- `POST /id/{user_id}/roles/{role_id}` - Requires `user:manage_roles` (Admin only)
- `DELETE /id/{user_id}/roles/{role_id}` - Requires `user:manage_roles` (Admin only)

#### Roles (`/api/v1/roles`) - NEW
- `GET /` - Requires `admin` (Admin only)
- `GET /{role_id}` - Requires `admin` (Admin only)
- `POST /` - Requires `admin` (Admin only)
- `DELETE /{role_id}` - Requires `admin` (Admin only, system roles protected)

### ✅ System Roles

#### 1. Administrator (`admin`)
- **Permissions:** `admin` (grants all permissions)
- **Description:** Full system access. Can manage users, settings, and all resources.
- **Use Case:** System administrators, superusers

#### 2. Product Owner (`po`)
- **Permissions:** 18 permissions including:
  - Project: view, create, update, delete
  - Task: view, create, update, delete
  - Sprint: view, create, update, delete
  - Analytics: view
  - Settings: view
- **Description:** Manage projects, sprints, and view analytics. Primary stakeholder role.
- **Use Case:** Product owners, project managers

#### 3. Developer (`developer`)
- **Permissions:** 10 permissions including:
  - Project: view
  - Task: view, create, update
  - Sprint: view
  - Analytics: view
- **Description:** Create and update tasks, view project data. Team member role.
- **Use Case:** Development team members

#### 4. QA Engineer (`qa`)
- **Permissions:** 11 permissions including:
  - Project: view
  - Task: view, update
  - Sprint: view
  - Quality: view, manage
  - Test: view, manage
  - Analytics: view
- **Description:** Manage quality metrics, tests, and view project data.
- **Use Case:** Quality assurance engineers

#### 5. Viewer (`viewer`)
- **Permissions:** 9 read-only permissions:
  - Project: view
  - Task: view
  - Sprint: view
  - Analytics: view
  - Quality: view
  - Test: view
  - Settings: view
- **Description:** Read-only access to projects, analytics, and reports.
- **Use Case:** Stakeholders, observers

## Permission Reference

### Permission Format
`"resource:action"`

**Resources:** project, task, sprint, user, settings, integration, quality, test, analytics, traceability, knowledge

**Actions:** view, create, update, delete, manage

**Special:** `admin` (superuser permission - grants all)

### Full Permission List

#### System
- `admin` - Superuser permission (grants all)

#### Projects
- `project:view`
- `project:create`
- `project:update`
- `project:delete`
- `project:manage` (includes all project operations)

#### Tasks
- `task:view`
- `task:create`
- `task:update`
- `task:delete`

#### Sprints
- `sprint:view`
- `sprint:create`
- `sprint:update`
- `sprint:delete`

#### Users
- `user:view`
- `user:create`
- `user:update`
- `user:delete`
- `user:manage` (user CRUD operations)
- `user:manage_roles` (role assignment/removal)

#### Settings & Integrations
- `settings:view`
- `settings:update`
- `integration:manage`

#### Quality & Testing
- `quality:view`
- `quality:manage`
- `test:view`
- `test:manage`

#### Analytics & Knowledge
- `analytics:view`
- `traceability:view`
- `knowledge:view`

## Usage Examples

### Check Permission in Code
```python
from app.api.deps import require_permission
from app.models import Permissions

@router.post("/projects")
async def create_project(
    project: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission(Permissions.PROJECT_CREATE))
):
    # Only users with project:create permission can access this endpoint
    ...
```

### Check Role in Code
```python
from app.api.deps import require_role

@router.get("/admin-dashboard")
async def admin_dashboard(
    current_user: User = Depends(require_role("admin"))
):
    # Only users with admin role can access this endpoint
    ...
```

### Assign Role to User (API)
```bash
# Assign 'po' role to user with ID 5
POST /api/v1/users/id/5/roles/2
Authorization: Bearer <admin-token>
```

### Remove Role from User (API)
```bash
# Remove role from user
DELETE /api/v1/users/id/5/roles/2
Authorization: Bearer <admin-token>
```

## Database Schema

### `roles` Table
```sql
CREATE TABLE roles (
    id INTEGER PRIMARY KEY,
    name VARCHAR UNIQUE NOT NULL,  -- e.g., 'admin', 'po'
    display_name VARCHAR NOT NULL,  -- e.g., 'Administrator'
    description VARCHAR,
    is_system BOOLEAN DEFAULT 0,  -- System roles cannot be deleted
    permissions VARCHAR,  -- JSON array of permissions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

### `user_roles` Table
```sql
CREATE TABLE user_roles (
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, role_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE
);
```

## Migration & Seeding

### Run Migration
```bash
cd backend
python -m alembic upgrade head
```

### Seed System Roles
```bash
cd backend
python scripts/seed_roles.py
```

**Note:** Seed script is idempotent - safe to run multiple times. It will:
- Create missing roles
- Update existing roles with latest permissions
- Never delete existing roles or user assignments

### Backward Compatibility
- Migration automatically assigns `admin` role to all existing superusers
- `is_superuser` flag still works and grants all permissions
- Gradual migration path: can use both old and new systems

## Security Considerations

1. **Permission Checking:** All protected endpoints verify permissions via FastAPI dependencies
2. **Logging:** Permission denials are logged with user and permission details
3. **Eager Loading:** User roles are eagerly loaded in `get_current_user` to prevent N+1 queries
4. **System Roles:** Protected from deletion (cannot delete roles with `is_system=True`)
5. **Admin Permission:** Special `admin` permission grants all access, simplifies superuser management

## Files Modified/Created

### New Files
- `backend/app/models/rbac.py` - RBAC models and permission definitions
- `backend/app/api/api_v1/endpoints/roles.py` - Role management endpoints
- `backend/alembic/versions/017_add_rbac_tables.py` - Database migration
- `backend/scripts/seed_roles.py` - Role seeding script
- `RBAC_IMPLEMENTATION.md` - This documentation

### Modified Files
- `backend/app/models/user.py` - Added roles relationship and permission methods
- `backend/app/models/__init__.py` - Export RBAC models
- `backend/app/api/deps.py` - Added permission checking dependencies
- `backend/app/schemas/user.py` - Added Role schema
- `backend/app/api/api_v1/api.py` - Registered roles router
- `backend/app/api/api_v1/endpoints/projects.py` - Applied permissions
- `backend/app/api/api_v1/endpoints/tasks.py` - Applied permissions
- `backend/app/api/api_v1/endpoints/settings.py` - Applied permissions
- `backend/app/api/api_v1/endpoints/users.py` - Added role management endpoints

## Testing Recommendations

1. **Test Permission Checking:**
   - Create users with different roles
   - Verify each role can only access permitted endpoints
   - Test permission denial returns 403 Forbidden

2. **Test Role Assignment:**
   - Assign/remove roles as admin
   - Verify non-admin cannot manage roles
   - Check user permissions update after role changes

3. **Test System Roles:**
   - Verify system roles cannot be deleted
   - Test superuser flag still grants all access
   - Check admin role grants all permissions

4. **Test Edge Cases:**
   - User with no roles (should be denied)
   - User with multiple roles (permissions combine)
   - Deleted role (user loses permissions)

## Next Steps (Optional Enhancements)

1. **Frontend Integration:**
   - Add role management UI for admins
   - Show/hide UI elements based on user permissions
   - Display user's current roles and permissions

2. **Permission Groups:**
   - Create permission bundles for common scenarios
   - Simplify role creation with preset groups

3. **Audit Logging:**
   - Log all role assignments/removals
   - Track permission changes over time
   - Alert on suspicious permission grants

4. **Dynamic Permissions:**
   - Allow creating custom permissions at runtime
   - Support resource-level permissions (e.g., "project:5:view")

5. **Permission Inheritance:**
   - Hierarchical roles (e.g., admin inherits from po)
   - Role templates for quick setup

## Conclusion

✅ **RBAC is fully implemented and operational.**

The system now has:
- Fine-grained permission control
- 5 predefined system roles
- Protected API endpoints
- Role management endpoints
- Complete backward compatibility

**To restart backend and see changes:**
```bash
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
