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


class AdsSalesBrandTurnoverItem(AdsBase):
    __tablename__ = "ads_sales_brand_turnover_item"
    __table_args__ = (
        Index(
            "idx_ads_sales_brand_turnover_filter",
            "data_version",
            "sales_date",
            "warehouse",
            "product_type",
            "brand",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    product_key: Mapped[str] = mapped_column(String(768), nullable=False)
    product_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    product: Mapped[str | None] = mapped_column(String(512), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)


class AdsSalesBrandTurnoverOrder(AdsBase):
    __tablename__ = "ads_sales_brand_turnover_order"
    __table_args__ = (
        Index(
            "idx_ads_sales_brand_turnover_order_filter",
            "data_version",
            "sales_date",
            "warehouse",
            "product_type",
            "brand",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    product_type: Mapped[str] = mapped_column(String(64), nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)


class AdsSalesDetailDailyChannel(AdsBase):
    __tablename__ = "ads_sales_detail_daily_channel"

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesOrderDetail(AdsBase):
    __tablename__ = "ads_sales_order_detail"
    __table_args__ = (
        Index(
            "idx_ads_sales_order_detail_filter",
            "data_version",
            "sales_date",
            "channel",
            "status",
        ),
        Index(
            "idx_ads_sales_order_detail_order",
            "data_version",
            "order_number",
        ),
        Index(
            "idx_ads_sales_order_detail_page",
            "data_version",
            "sales_time",
            "order_number",
        ),
        Index(
            "idx_ads_sales_order_detail_filter_page",
            "data_version",
            "channel",
            "status",
            "sales_time",
            "order_number",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    sales_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    order_number: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_status: Mapped[str] = mapped_column(String(64), nullable=False)
    product: Mapped[str] = mapped_column(String(1024), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    receivable_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    city: Mapped[str] = mapped_column(String(128), nullable=False)


class AdsSalesOrderDailyFilter(AdsBase):
    __tablename__ = "ads_sales_order_daily_filter"
    __table_args__ = (
        Index(
            "idx_ads_sales_order_daily_filter",
            "data_version",
            "sales_date",
            "channel",
            "status",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), primary_key=True)
    detail_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyChannelCustomer(AdsBase):
    __tablename__ = "ads_sales_daily_channel_customer"
    __table_args__ = (
        Index(
            "idx_ads_sales_channel_customer_filter",
            "data_version",
            "channel",
            "sales_date",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    customer_code: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesCustomerDaily(AdsBase):
    __tablename__ = "ads_sales_customer_daily"
    __table_args__ = (
        Index("idx_ads_customer_daily_brand", "data_version", "brand", "sales_date", "customer_code"),
        Index("idx_ads_customer_daily_channel", "data_version", "channel", "sales_date", "customer_code"),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesCustomerProductDaily(AdsBase):
    __tablename__ = "ads_sales_customer_product_daily"
    __table_args__ = (
        Index("idx_ads_customer_product_brand", "data_version", "brand", "sales_date", "product_code"),
        Index("idx_ads_customer_product_channel", "data_version", "channel", "sales_date", "product_code"),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_code: Mapped[str] = mapped_column(String(128), nullable=False)
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesCustomerQualityDaily(AdsBase):
    __tablename__ = "ads_sales_customer_quality_daily"
    __table_args__ = (
        Index("idx_ads_customer_quality_brand", "data_version", "brand", "sales_date"),
        Index("idx_ads_customer_quality_channel", "data_version", "channel", "sales_date"),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False)
    brand: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(255), nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    identified_orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    identified_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)


class AdsSalesDailyBrandChannelScope(AdsBase):
    __tablename__ = "ads_sales_daily_brand_channel_scope"
    __table_args__ = (
        Index(
            "idx_ads_sales_brand_channel_scope_filter",
            "data_version",
            "brand",
            "sales_date",
            "product_type_scope",
            "channel",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    brand: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_type_scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    detail_rows: Mapped[int] = mapped_column(BigInteger, nullable=False)
    orders: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)


class AdsSalesDailyBrandChannelProduct(AdsBase):
    __tablename__ = "ads_sales_daily_brand_channel_product"
    __table_args__ = (
        Index(
            "idx_ads_sales_brand_channel_product_filter",
            "data_version",
            "brand",
            "sales_date",
            "channel",
            "product_type",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    sales_date: Mapped[date] = mapped_column(Date, primary_key=True)
    brand: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    product: Mapped[str] = mapped_column(String(255), primary_key=True)
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
    stock_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    sales30: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    sales90: Mapped[Decimal] = mapped_column(Numeric(24, 4), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdsInventoryArrivalItem(AdsBase):
    __tablename__ = "ads_inventory_arrival_item"
    __table_args__ = (
        Index(
            "idx_ads_inventory_arrival_filter",
            "data_version",
            "receipt_date",
            "warehouse",
        ),
        Index(
            "idx_ads_inventory_arrival_detail",
            "data_version",
            "receipt_time",
            "receipt_number",
            "rec_id",
        ),
    )

    data_version: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    receipt_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    receipt_year: Mapped[int] = mapped_column(Integer, nullable=False)
    doc_id: Mapped[str] = mapped_column(String(32), nullable=False)
    rec_id: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt_number: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warehouse: Mapped[str] = mapped_column(String(255), nullable=False)
    warehouse_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reversal_status: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product: Mapped[str | None] = mapped_column(String(512), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_type: Mapped[str] = mapped_column(String(255), nullable=False)
    product_type_raw: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    batch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    production_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
