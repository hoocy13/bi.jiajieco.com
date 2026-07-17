from pydantic import BaseModel, Field


class ModelSettingUpdate(BaseModel):
    base_url: str = Field(min_length=8, max_length=512)
    model_id: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, max_length=2048)
