from uuid import UUID

from pydantic import BaseModel, Field


class RagSearchRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)


class RagConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class RagRunCreate(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


class RagJobPublic(BaseModel):
    id: UUID
    document_version_id: UUID | None
    status: str
    error_code: str | None
    error_message: str | None
    started_at: str | None
    finished_at: str | None
