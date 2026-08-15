from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PermissionPublic(BaseModel):
    code: str
    name: str
    module: str

    model_config = ConfigDict(from_attributes=True)


class RolePublic(BaseModel):
    id: int
    role_no: str | None = None
    code: str
    name: str
    description: str
    is_system: bool
    is_active: bool
    permissions: list[PermissionPublic] = []
    user_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class UserPublic(BaseModel):
    id: int
    username: str
    email: str | None = None
    display_name: str | None = None
    phone: str | None = None
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    role: RolePublic | None = None
    permissions: list[str] = []

    model_config = ConfigDict(from_attributes=True)


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserRoleUpdate(BaseModel):
    role_id: int


class UserProfileUpdate(BaseModel):
    display_name: str = Field(min_length=2, max_length=64)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)


class UserCreate(BaseModel):
    username: str
    password: str


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(default="", max_length=255)
    permission_codes: list[str] = []


class RoleUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(default="", max_length=255)
    permission_codes: list[str] = []
