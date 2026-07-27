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


class AdsInventoryProductWarehouse(AdsBase):
    __tablename__ = "ads_inventory_product_warehouse"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    warehouse: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    product_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    records: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stock_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    stock_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    stock_min: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    stock_max: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdsInventoryBatchSummary(AdsBase):
    __tablename__ = "ads_inventory_batch_summary"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    warehouse: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_records: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expiring_batch_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdsInventoryFilterOption(AdsBase):
    __tablename__ = "ads_inventory_filter_option"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    option_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    option_value: Mapped[str] = mapped_column(String(255), primary_key=True)


class AdsInventoryHealthItem(AdsBase):
    __tablename__ = "ads_inventory_health_item"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    barcode: Mapped[str] = mapped_column(String(255), nullable=False)
    product: Mapped[str] = mapped_column(String(512), nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    sales30: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    sales90: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    stock_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    available_days: Mapped[Decimal | None] = mapped_column(Numeric(24, 1), nullable=True)
    issue_type: Mapped[str] = mapped_column(String(32), nullable=False)


class AdsInventoryTurnoverItem(AdsBase):
    __tablename__ = "ads_inventory_turnover_item"
    __table_args__ = (
        Index(
            "idx_ads_inventory_turnover_filter",
            "data_version",
            "warehouse",
            "product_type",
            "stock",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product: Mapped[str | None] = mapped_column(String(512), nullable=True)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    sales30: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsInventoryBatchItem(AdsBase):
    __tablename__ = "ads_inventory_batch_item"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product: Mapped[str | None] = mapped_column(String(512), nullable=True)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    batch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
