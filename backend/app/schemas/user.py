from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, Field


# Role schemas
class RoleBase(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    permissions: List[str] = Field(default_factory=list)


class Role(RoleBase):
    id: int
    is_system: bool
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# User schemas
class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class UserInDB(UserBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class User(UserInDB):
    """User schema with roles for API responses."""

    roles: List[Role] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class ScopedTokenRequest(BaseModel):
    """Request body for issuing a scoped access token."""

    scopes: List[str] = Field(default_factory=list)
    expires_minutes: int = Field(..., gt=0)
    tenant_id: Optional[str] = None


class TokenData(BaseModel):
    username: Optional[str] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str
