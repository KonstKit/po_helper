"""
RBAC (Role-Based Access Control) models.

This module implements a flexible RBAC system with:
- Predefined roles: Admin, PO (Product Owner), Developer, QA, Viewer
- Granular permissions for different resource types
- Many-to-many relationship between users and roles
- Permission checking at API level

Design:
- Role: A named collection of permissions (e.g., "Admin", "PO")
- Permission: A specific capability (e.g., "project:create", "settings:update")
- UserRole: Association table linking users to roles
"""

from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


# Association table for many-to-many User-Role relationship
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role_id', Integer, ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    Column('assigned_at', DateTime(timezone=True), server_default=func.now()),
)


class Role(Base):
    """
    Role model representing a named collection of permissions.

    Predefined roles:
    - admin: Full system access
    - po: Product Owner - manage projects, view all data
    - developer: Create/edit tasks, view project data
    - qa: View and test, manage quality metrics
    - viewer: Read-only access

    Attributes:
        id: Primary key
        name: Unique role identifier (e.g., 'admin', 'po', 'developer')
        display_name: Human-readable name (e.g., 'Administrator', 'Product Owner')
        description: Role description
        is_system: System-defined role (cannot be deleted)
        permissions: JSON array of permission strings
        created_at: Timestamp when role was created
        updated_at: Timestamp when role was last updated
    """
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)  # e.g., 'admin', 'po'
    display_name = Column(String, nullable=False)  # e.g., 'Administrator'
    description = Column(String, nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # System roles cannot be deleted

    # JSON array of permission strings, e.g., ['project:create', 'project:update', 'project:delete']
    # Using String column to store JSON for SQLite compatibility
    # Format: "permission1,permission2,permission3" or JSON string "['perm1', 'perm2']"
    permissions_str = Column('permissions', String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to users
    users = relationship("User", secondary=user_roles, back_populates="roles")

    @property
    def permissions(self) -> list[str]:
        """Get permissions as a list."""
        if not self.permissions_str:
            return []
        # Handle both comma-separated and JSON formats
        import json
        try:
            # Try JSON first
            return json.loads(self.permissions_str)
        except (json.JSONDecodeError, TypeError):
            # Fall back to comma-separated
            return [p.strip() for p in self.permissions_str.split(',') if p.strip()]

    @permissions.setter
    def permissions(self, value: list[str]):
        """Set permissions from a list."""
        import json
        self.permissions_str = json.dumps(value) if value else None

    def has_permission(self, permission: str) -> bool:
        """Check if this role has a specific permission."""
        return permission in self.permissions

    def __repr__(self):
        return f"<Role(name='{self.name}', display_name='{self.display_name}')>"


# Permission constants (centralized for easy maintenance)
class Permissions:
    """
    Centralized permission definitions.

    Format: "resource:action"
    Resources: project, task, sprint, user, settings, integration, quality, analytics, traceability
    Actions: view, create, update, delete, manage, test
    Special: admin (superuser permission)
    """

    # System
    ADMIN = "admin"  # Superuser permission

    # Projects
    PROJECT_VIEW = "project:view"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_MANAGE = "project:manage"  # Includes all project operations

    # Tasks
    TASK_VIEW = "task:view"
    TASK_CREATE = "task:create"
    TASK_UPDATE = "task:update"
    TASK_DELETE = "task:delete"

    # Sprints
    SPRINT_VIEW = "sprint:view"
    SPRINT_CREATE = "sprint:create"
    SPRINT_UPDATE = "sprint:update"
    SPRINT_DELETE = "sprint:delete"

    # Users
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_MANAGE = "user:manage"  # Includes user CRUD operations
    USER_MANAGE_ROLES = "user:manage_roles"  # Role assignment/removal

    # Settings & Integrations
    SETTINGS_VIEW = "settings:view"
    SETTINGS_UPDATE = "settings:update"
    INTEGRATION_MANAGE = "integration:manage"

    # Quality & Testing
    QUALITY_VIEW = "quality:view"
    QUALITY_MANAGE = "quality:manage"
    TEST_VIEW = "test:view"
    TEST_MANAGE = "test:manage"

    # Analytics & Traceability
    ANALYTICS_VIEW = "analytics:view"
    TRACEABILITY_VIEW = "traceability:view"
    TRACEABILITY_MANAGE = "traceability:manage"

    # Confluence & Knowledge
    KNOWLEDGE_VIEW = "knowledge:view"
    KNOWLEDGE_MANAGE = "knowledge:manage"


# Predefined role configurations
SYSTEM_ROLES = {
    "admin": {
        "display_name": "Administrator",
        "description": "Full system access. Can manage users, settings, and all resources.",
        "is_system": True,
        "permissions": [
            Permissions.ADMIN,  # Superuser permission (grants all)
        ],
    },
    "po": {
        "display_name": "Product Owner",
        "description": "Manage projects, sprints, and view analytics. Primary stakeholder role.",
        "is_system": True,
        "permissions": [
            # Projects
            Permissions.PROJECT_VIEW,
            Permissions.PROJECT_CREATE,
            Permissions.PROJECT_UPDATE,
            Permissions.PROJECT_DELETE,
            # Tasks
            Permissions.TASK_VIEW,
            Permissions.TASK_CREATE,
            Permissions.TASK_UPDATE,
            Permissions.TASK_DELETE,
            # Sprints
            Permissions.SPRINT_VIEW,
            Permissions.SPRINT_CREATE,
            Permissions.SPRINT_UPDATE,
            Permissions.SPRINT_DELETE,
            # Analytics
            Permissions.ANALYTICS_VIEW,
            Permissions.QUALITY_VIEW,
            Permissions.TEST_VIEW,
            Permissions.TRACEABILITY_VIEW,
            Permissions.KNOWLEDGE_VIEW,
            # Settings (view only)
            Permissions.SETTINGS_VIEW,
        ],
    },
    "developer": {
        "display_name": "Developer",
        "description": "Create and update tasks, view project data. Team member role.",
        "is_system": True,
        "permissions": [
            # Projects (view only)
            Permissions.PROJECT_VIEW,
            # Tasks
            Permissions.TASK_VIEW,
            Permissions.TASK_CREATE,
            Permissions.TASK_UPDATE,
            # Sprints (view only)
            Permissions.SPRINT_VIEW,
            # Analytics
            Permissions.ANALYTICS_VIEW,
            Permissions.QUALITY_VIEW,
            Permissions.TEST_VIEW,
            Permissions.TRACEABILITY_VIEW,
            Permissions.KNOWLEDGE_VIEW,
        ],
    },
    "qa": {
        "display_name": "QA Engineer",
        "description": "Manage quality metrics, tests, and view project data. Quality assurance role.",
        "is_system": True,
        "permissions": [
            # Projects (view only)
            Permissions.PROJECT_VIEW,
            # Tasks (view + update for testing)
            Permissions.TASK_VIEW,
            Permissions.TASK_UPDATE,
            # Sprints (view only)
            Permissions.SPRINT_VIEW,
            # Quality & Testing
            Permissions.QUALITY_VIEW,
            Permissions.QUALITY_MANAGE,
            Permissions.TEST_VIEW,
            Permissions.TEST_MANAGE,
            # Analytics
            Permissions.ANALYTICS_VIEW,
            Permissions.TRACEABILITY_VIEW,
            Permissions.KNOWLEDGE_VIEW,
        ],
    },
    "viewer": {
        "display_name": "Viewer",
        "description": "Read-only access to projects, analytics, and reports. Stakeholder role.",
        "is_system": True,
        "permissions": [
            # View everything, modify nothing
            Permissions.PROJECT_VIEW,
            Permissions.TASK_VIEW,
            Permissions.SPRINT_VIEW,
            Permissions.ANALYTICS_VIEW,
            Permissions.QUALITY_VIEW,
            Permissions.TEST_VIEW,
            Permissions.TRACEABILITY_VIEW,
            Permissions.KNOWLEDGE_VIEW,
            Permissions.SETTINGS_VIEW,
        ],
    },
}
