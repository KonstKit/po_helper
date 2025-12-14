from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)  # Legacy superuser flag (still used for backward compatibility)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # RBAC: Many-to-many relationship with roles
    roles = relationship("Role", secondary="user_roles", back_populates="users")

    # Traceability rules created by this user
    traceability_rules = relationship("TraceabilityRule", back_populates="created_by")

    def has_permission(self, permission: str) -> bool:
        """
        Check if user has a specific permission.

        Args:
            permission: Permission string (e.g., 'project:create')

        Returns:
            True if user has the permission (via roles or is_superuser)
        """
        # Superusers have all permissions
        if self.is_superuser:
            return True

        # Check if any of the user's roles have the permission
        for role in self.roles:
            if permission in role.permissions or "admin" in role.permissions:
                return True

        return False

    def has_role(self, role_name: str) -> bool:
        """
        Check if user has a specific role.

        Args:
            role_name: Role name (e.g., 'admin', 'po')

        Returns:
            True if user has the role
        """
        return any(role.name == role_name for role in self.roles)