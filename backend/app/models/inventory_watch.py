from datetime import datetime

from sqlalchemy import DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InventoryWatch(Base):
    __tablename__ = "inventory_channel_watches"
    __table_args__ = (
        UniqueConstraint("channel_code", "product_code", name="uq_inventory_watch_channel_product"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(128), index=True)
    channel_name: Mapped[str] = mapped_column(String(255))
    product_code: Mapped[str] = mapped_column(String(128), index=True)
    product_name: Mapped[str] = mapped_column(String(512))
    note: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(default=1)
    created_by: Mapped[int] = mapped_column()
    updated_by: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class InventoryWatchAudit(Base):
    __tablename__ = "inventory_watch_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_code: Mapped[str] = mapped_column(String(128))
    product_code: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    actor_id: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
