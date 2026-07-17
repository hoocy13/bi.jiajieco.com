from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ModelSetting(Base):
    __tablename__ = "model_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    provider: Mapped[str] = mapped_column(String(64), default="OpenAI Compatible")
    base_url: Mapped[str] = mapped_column(String(512))
    model_id: Mapped[str] = mapped_column(String(255))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
