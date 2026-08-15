from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnnouncementPayload(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    content: str = Field(min_length=2, max_length=2000)
    is_active: bool = False


class AnnouncementPublic(BaseModel):
    id: int
    title: str
    content: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
