from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.mysql import LONGBLOB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.ads import AdsBase


class AdsMonthlyProfitSource(AdsBase):
    __tablename__ = 'ads_monthly_profit_source'
    __table_args__ = (Index('idx_monthly_profit_month', 'month', 'created_at'),)

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    rules_version: Mapped[str] = mapped_column(String(32), nullable=False)
    code_collation: Mapped[str] = mapped_column(String(64), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), 'mysql'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AdsMonthlyProfitSku(AdsBase):
    __tablename__ = 'ads_monthly_profit_sku'

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_code: Mapped[str] = mapped_column(
        String(255, collation='utf8mb4_bin').with_variant(String(255, collation='BINARY'), 'sqlite'),
        primary_key=True,
    )
