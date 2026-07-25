from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, Index, Integer, JSON, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class AdsBase(DeclarativeBase):
    pass


class AdsPublishBatch(AdsBase):
    __tablename__ = "ads_publish_batch"
    __table_args__ = (
        Index("idx_ads_publish_dataset_status", "dataset", "status", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data_version: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    dataset: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    daily_row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    channel_row_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reconciliation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdsSalesDaily(AdsBase):
    __tablename__ = "ads_sales_daily"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyChannel(AdsBase):
    __tablename__ = "ads_sales_daily_channel"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyCityChannel(AdsBase):
    __tablename__ = "ads_sales_daily_city_channel"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    city: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDetailDaily(AdsBase):
    __tablename__ = "ads_sales_detail_daily"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyProduct(AdsBase):
    __tablename__ = "ads_sales_daily_product"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    product: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDetailDailyScope(AdsBase):
    __tablename__ = "ads_sales_detail_daily_scope"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    product_type_scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyBrandScope(AdsBase):
    __tablename__ = "ads_sales_daily_brand_scope"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    product_type_scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    brand: Mapped[str] = mapped_column(String(128), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyBrandProduct(AdsBase):
    __tablename__ = "ads_sales_daily_brand_product"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    brand: Mapped[str] = mapped_column(String(128), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    product: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDetailDailyChannel(AdsBase):
    __tablename__ = "ads_sales_detail_daily_channel"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
