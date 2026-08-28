from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.rbac import Role
    from app.models.traceability_rule import TraceabilityRule


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String)
    hashed_password: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now()
    )

    # OAuth2 SSO fields
    oauth_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    oauth_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oauth_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # MFA fields. mfa_secret stores an AES-GCM ciphertext (encgcm:...),
    # hence the 512 length; mfa_last_used_counter is the TOTP interval of
    # the most recently accepted code (anti-replay).
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mfa_backup_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    mfa_last_used_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # RBAC: Many-to-many relationship with roles
    roles: Mapped[list[Role]] = relationship("Role", secondary="user_roles", back_populates="users")

    # Traceability rules created by this user
    traceability_rules: Mapped[list[TraceabilityRule]] = relationship(
        "TraceabilityRule", back_populates="created_by"
    )

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

    @property
    def is_oauth_user(self) -> bool:
        """Check if this user was created via OAuth."""
        return self.oauth_provider is not None

    @property
    def can_set_password(self) -> bool:
        """Check if user can set/change password (OAuth users without password can set one)."""
        return True  # All users can set passwords

    @property
    def has_password(self) -> bool:
        """Check if user has a password set."""
        return self.hashed_password is not None and len(self.hashed_password) > 0

    @property
    def mfa_configured(self) -> bool:
        """Check if MFA is fully configured (has secret)."""
        return self.mfa_secret is not None and len(self.mfa_secret) > 0

    @property
    def remaining_backup_codes(self) -> int:
        """Get count of remaining MFA backup codes."""
        if self.mfa_backup_codes:
            return len(self.mfa_backup_codes)
        return 0
