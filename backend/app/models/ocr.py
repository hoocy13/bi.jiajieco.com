from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class OcrJob(Base):
    __tablename__ = "ocr_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    source: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    task: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(16), default="page")
    max_tokens: Mapped[int] = mapped_column(default=4096)
    prompt: Mapped[str] = mapped_column(Text, default="")
    fields: Mapped[str] = mapped_column(Text, default="")
    question: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    result: Mapped[str] = mapped_column(Text, default="", deferred=True)
    error: Mapped[str] = mapped_column(String(255), default="")
    pages_done: Mapped[int] = mapped_column(default=0)
    pages_total: Mapped[int] = mapped_column(default=0)
    regions_done: Mapped[int] = mapped_column(default=0)
    regions_total: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    lease: Mapped[str] = mapped_column(String(64), default="")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class OcrWorker(Base):
    __tablename__ = "ocr_workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ready: Mapped[bool] = mapped_column(default=False)
    region_ready: Mapped[bool] = mapped_column(default=False)
