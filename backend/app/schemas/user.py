from pydantic import BaseModel, ConfigDict


class UserPublic(BaseModel):
    id: int
    username: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserCreate(BaseModel):
    username: str
    password: str
