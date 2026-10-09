from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CoreCostPriceRevision(Base):
    __tablename__ = "core_cost_price_revisions"
    __table_args__ = (Index("ix_core_cost_sku_effective", "product_code", "effective_date", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_code: Mapped[str] = mapped_column(String(128), index=True)
    product_name: Mapped[str] = mapped_column(String(255), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    effective_date: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32))
    restored_from_id: Mapped[int | None] = mapped_column(ForeignKey("core_cost_price_revisions.id"), nullable=True)
    operator: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
