from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class GroupBuyBatch(Base):
    __tablename__ = "group_buy_batches"
    __table_args__ = (UniqueConstraint("month", "brand", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    brand: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    document: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class GroupBuyChange(Base):
    __tablename__ = "group_buy_changes"
    __table_args__ = (UniqueConstraint("batch_id", "revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("group_buy_batches.id"), index=True)
    revision: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column(String(32))
    changes: Mapped[dict] = mapped_column(JSON)
    operator: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
