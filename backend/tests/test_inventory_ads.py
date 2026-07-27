import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.api.routers.inventory as inventory_router
from app.core.config import settings
from app.jobs.build_inventory_ads import reconciliation_payload
from app.models.ads import (
    AdsBase,
    AdsInventoryBatchSummary,
    AdsInventoryBatchItem,
    AdsInventoryFilterOption,
    AdsInventoryHealthItem,
    AdsInventoryProductWarehouse,
    AdsInventoryTurnoverItem,
    AdsPublishBatch,
)
from app.services.inventory_ads import (
    latest_ready_inventory_batch,
    load_batch_expiry_from_ads,
    load_inventory_filter_options_from_ads,
    load_inventory_health_from_ads,
    load_inventory_overview_from_ads,
    load_inventory_turnover_from_ads,
)


class InventoryAdsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        AdsBase.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        batch = AdsPublishBatch(
            data_version="inventory-test-ready",
            dataset="inventory_overview",
            status="ready",
            source_start_date=date(2026, 7, 27),
            source_end_date=date(2026, 7, 27),
            created_at=datetime(2026, 7, 27, 1, 0),
            finished_at=datetime(2026, 7, 27, 1, 1),
            published_at=datetime(2026, 7, 27, 1, 1),
        )
        self.db.add(batch)
        today = datetime.now(timezone(timedelta(hours=8))).date()
        self.db.add_all(
            [
                AdsInventoryProductWarehouse(
                    data_version=batch.data_version,
                    warehouse="仓库A",
                    product_type="正装",
                    product_code="A",
                    records=2,
                    stock_quantity=Decimal("10"),
                    available_stock=Decimal("8"),
                    stock_amount=Decimal("100"),
                    stock_min=Decimal("5"),
                    stock_max=Decimal("7"),
                    updated_at=datetime(2026, 7, 27, 2, 0),
                ),
                AdsInventoryProductWarehouse(
                    data_version=batch.data_version,
                    warehouse="仓库B",
                    product_type="正装",
                    product_code="A",
                    records=1,
                    stock_quantity=Decimal("2"),
                    available_stock=Decimal("1"),
                    stock_amount=Decimal("20"),
                    stock_min=Decimal("5"),
                    stock_max=Decimal("7"),
                    updated_at=datetime(2026, 7, 27, 2, 0),
                ),
                AdsInventoryProductWarehouse(
                    data_version=batch.data_version,
                    warehouse="仓库A",
                    product_type="小样",
                    product_code="B",
                    records=1,
                    stock_quantity=Decimal("3"),
                    available_stock=Decimal("2"),
                    stock_amount=Decimal("30"),
                    stock_min=Decimal("3"),
                    stock_max=Decimal("10"),
                    updated_at=datetime(2026, 7, 27, 2, 0),
                ),
                AdsInventoryBatchSummary(
                    data_version=batch.data_version,
                    warehouse="仓库A",
                    product_type="正装",
                    batch_records=4,
                    expiring_batch_count=1,
                    updated_at=datetime(2026, 7, 27, 3, 0),
                ),
                AdsInventoryBatchSummary(
                    data_version=batch.data_version,
                    warehouse="仓库A",
                    product_type="小样",
                    batch_records=2,
                    expiring_batch_count=2,
                    updated_at=datetime(2026, 7, 27, 3, 0),
                ),
                AdsInventoryFilterOption(
                    data_version=batch.data_version,
                    option_type="warehouse",
                    option_value="仓库A",
                ),
                AdsInventoryFilterOption(
                    data_version=batch.data_version,
                    option_type="warehouse",
                    option_value="仓库B",
                ),
                AdsInventoryFilterOption(
                    data_version=batch.data_version,
                    option_type="product_type",
                    option_value="正装",
                ),
                AdsInventoryFilterOption(
                    data_version=batch.data_version,
                    option_type="product_type",
                    option_value="小样",
                ),
                AdsInventoryFilterOption(
                    data_version=batch.data_version,
                    option_type="brand",
                    option_value="品牌A",
                ),
                AdsInventoryHealthItem(
                    data_version=batch.data_version,
                    item_id=1,
                    product_code="A",
                    barcode="BAR-A",
                    product="商品A",
                    brand="品牌A",
                    product_type="正装",
                    warehouse="仓库A",
                    stock=Decimal("10"),
                    available_stock=Decimal("8"),
                    sales30=Decimal("30"),
                    sales90=Decimal("90"),
                    stock_amount=Decimal("100"),
                    available_days=Decimal("8.0"),
                    issue_type="shortage",
                ),
                AdsInventoryHealthItem(
                    data_version=batch.data_version,
                    item_id=2,
                    product_code="B",
                    barcode="-",
                    product="商品B",
                    brand="品牌B",
                    product_type="小样",
                    warehouse="仓库A",
                    stock=Decimal("3"),
                    available_stock=Decimal("2"),
                    sales30=Decimal("0"),
                    sales90=Decimal("0"),
                    stock_amount=Decimal("30"),
                    available_days=None,
                    issue_type="missing_barcode",
                ),
                AdsInventoryHealthItem(
                    data_version=batch.data_version,
                    item_id=3,
                    product_code="C",
                    barcode="BAR-C",
                    product="商品C",
                    brand="品牌A",
                    product_type="正装",
                    warehouse="仓库B",
                    stock=Decimal("2"),
                    available_stock=Decimal("2"),
                    sales30=Decimal("0"),
                    sales90=Decimal("1"),
                    stock_amount=Decimal("20"),
                    available_days=None,
                    issue_type="healthy",
                ),
                AdsInventoryBatchItem(
                    data_version=batch.data_version,
                    item_id=1,
                    warehouse="仓库A",
                    product_code="A",
                    barcode="BAR-A",
                    product="商品A",
                    brand="品牌A",
                    product_type="正装",
                    batch="B1",
                    production_date=today - timedelta(days=100),
                    expiry_date=today + timedelta(days=10),
                    stock=Decimal("10"),
                    available_stock=Decimal("8"),
                    updated_at=datetime(2026, 7, 27, 3, 0),
                ),
                AdsInventoryBatchItem(
                    data_version=batch.data_version,
                    item_id=2,
                    warehouse="仓库A",
                    product_code="A",
                    barcode="BAR-A",
                    product="商品A",
                    brand="品牌A",
                    product_type="正装",
                    batch="B2",
                    production_date=today - timedelta(days=10),
                    expiry_date=today + timedelta(days=800),
                    stock=Decimal("4"),
                    available_stock=Decimal("3"),
                    updated_at=datetime(2026, 7, 27, 3, 0),
                ),
                AdsInventoryBatchItem(
                    data_version=batch.data_version,
                    item_id=3,
                    warehouse="仓库A",
                    product_code="B",
                    barcode=None,
                    product="商品B",
                    brand="品牌B",
                    product_type="小样",
                    batch=None,
                    production_date=None,
                    expiry_date=None,
                    stock=Decimal("2"),
                    available_stock=Decimal("2"),
                    updated_at=datetime(2026, 7, 27, 3, 0),
                ),
                AdsInventoryTurnoverItem(
                    data_version=batch.data_version,
                    item_id=1,
                    product_code="A",
                    barcode="BAR-A",
                    product="商品A",
                    brand="品牌A",
                    product_type="正装",
                    warehouse="仓库A",
                    stock=Decimal("200"),
                    available_stock=Decimal("180"),
                    sales30=Decimal("100"),
                ),
                AdsInventoryTurnoverItem(
                    data_version=batch.data_version,
                    item_id=2,
                    product_code="B",
                    barcode=None,
                    product="商品B",
                    brand="品牌B",
                    product_type="小样",
                    warehouse="仓库A",
                    stock=Decimal("150"),
                    available_stock=Decimal("140"),
                    sales30=Decimal("0"),
                ),
                AdsInventoryTurnoverItem(
                    data_version=batch.data_version,
                    item_id=3,
                    product_code="C",
                    barcode="BAR-C",
                    product="商品C",
                    brand="品牌A",
                    product_type="正装",
                    warehouse="仓库B",
                    stock=Decimal("80"),
                    available_stock=Decimal("70"),
                    sales30=Decimal("20"),
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_loads_filter_options(self) -> None:
        batch = latest_ready_inventory_batch(self.db)
        data = load_inventory_filter_options_from_ads(self.db, batch)
        self.assertEqual(data["warehouses"], ["仓库A", "仓库B"])
        self.assertEqual(data["product_types"], ["正装", "小样"])
        self.assertEqual(data["brands"], ["品牌A"])

    def test_loads_default_and_combination_filters(self) -> None:
        batch = latest_ready_inventory_batch(self.db)
        data = load_inventory_overview_from_ads(
            self.db,
            batch,
            warehouses=(),
            product_types=("小样", "正装"),
        )
        self.assertEqual(data["metrics"]["product_count"], 2)
        self.assertEqual(data["metrics"]["warehouse_records"], 4)
        self.assertEqual(data["metrics"]["available_stock"], 11)
        self.assertEqual(data["metrics"]["stock_amount"], 150)
        self.assertEqual(data["metrics"]["below_min_count"], 1)
        self.assertEqual(data["metrics"]["above_max_count"], 1)
        self.assertEqual(data["metrics"]["batch_records"], 6)
        self.assertEqual(data["metrics"]["expiring_batch_count"], 3)
        self.assertEqual(data["warehouses"][0]["warehouse"], "仓库A")

        filtered = load_inventory_overview_from_ads(
            self.db,
            batch,
            warehouses=("仓库A",),
            product_types=("正装",),
        )
        self.assertEqual(filtered["metrics"]["product_count"], 1)
        self.assertEqual(filtered["metrics"]["warehouse_records"], 2)
        self.assertEqual(filtered["metrics"]["available_stock"], 8)
        self.assertEqual(filtered["metrics"]["batch_records"], 4)

    def test_router_uses_ads(self) -> None:
        original_mode = settings.BI_QUERY_SOURCE
        original_session = inventory_router.AdsSessionLocal
        try:
            settings.BI_QUERY_SOURCE = "ads"
            inventory_router.AdsSessionLocal = sessionmaker(bind=self.engine)
            inventory_router._inventory_cache.clear()
            response = Response()
            payload = inventory_router.inventory_overview(
                response=response,
                warehouse=["仓库A"],
                product_type=["正装"],
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(payload["data"]["metrics"]["available_stock"], 8)

            response = Response()
            options = inventory_router.inventory_warehouses(
                response=response,
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(options["data"]["warehouses"], ["仓库A", "仓库B"])

            response = Response()
            health = inventory_router.inventory_health(
                response=response,
                keyword=None,
                barcode=None,
                warehouse=["仓库A"],
                product_type=["正装", "小样"],
                issue_type="all",
                page=1,
                page_size=50,
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(health["data"]["pagination"]["total"], 2)

            response = Response()
            expiry = inventory_router.batch_expiry_analysis(
                response=response,
                keyword=None,
                barcode=None,
                warehouse=["仓库A"],
                product_type=["正装", "小样"],
                expiry_range="all",
                page=1,
                long_page=1,
                page_size=50,
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(expiry["data"]["metrics"]["batch_count"], 3)

            response = Response()
            turnover = inventory_router.inventory_turnover(
                response=response,
                keyword=None,
                barcode=None,
                min_stock=100,
                warehouse=["仓库A"],
                product_type=["正装", "小样"],
                page=1,
                page_size=50,
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(turnover["data"]["pagination"]["total"], 2)
        finally:
            settings.BI_QUERY_SOURCE = original_mode
            inventory_router.AdsSessionLocal = original_session
            inventory_router._inventory_cache.clear()

    def test_loads_health_filters_and_pagination(self) -> None:
        batch = latest_ready_inventory_batch(self.db)
        data = load_inventory_health_from_ads(
            self.db,
            batch,
            keyword="商品",
            barcode="BAR",
            warehouses=(),
            product_types=("正装", "小样"),
            issue_type="all",
            page=1,
            page_size=10,
        )
        self.assertEqual(data["metrics"]["item_count"], 2)
        self.assertEqual(data["metrics"]["shortage_count"], 1)
        self.assertEqual(data["pagination"]["total"], 1)
        self.assertEqual(data["rows"][0]["product_code"], "A")
        self.assertEqual(data["rows"][0]["available_days"], 8)

    def test_loads_batch_expiry_and_fefo(self) -> None:
        batch = latest_ready_inventory_batch(self.db)
        data = load_batch_expiry_from_ads(
            self.db,
            batch,
            keyword="商品A",
            barcode="BAR",
            warehouses=("仓库A",),
            product_types=("正装",),
            expiry_range="all",
            page=1,
            long_page=1,
            page_size=10,
        )
        self.assertEqual(data["metrics"]["batch_count"], 2)
        self.assertEqual(data["metrics"]["product_count"], 1)
        self.assertEqual(data["pagination"]["total"], 2)
        self.assertEqual(data["fefo_rows"][0]["fefo_rank"], 1)
        self.assertEqual(data["fefo_rows"][0]["remaining_days"], 10)
        self.assertEqual(data["long_pagination"]["total"], 1)
        self.assertEqual(data["long_expiry_rows"][0]["batch_count"], 1)

    def test_loads_product_turnover_filters_and_pagination(self) -> None:
        batch = latest_ready_inventory_batch(self.db)
        data = load_inventory_turnover_from_ads(
            self.db,
            batch,
            keyword="商品",
            barcode="BAR",
            min_stock=50,
            warehouses=(),
            product_types=("正装", "小样"),
            page=1,
            page_size=10,
        )
        self.assertEqual(data["pagination"]["total"], 2)
        self.assertEqual(data["rows"][0]["product_code"], "C")
        self.assertEqual(data["rows"][0]["turnover_days"], 120)
        self.assertEqual(data["rows"][0]["status"], "偏慢")
        self.assertEqual(data["rows"][1]["product_code"], "A")
        self.assertEqual(data["rows"][1]["turnover_days"], 60)

        no_sales = load_inventory_turnover_from_ads(
            self.db,
            batch,
            keyword="商品B",
            barcode="",
            min_stock=100,
            warehouses=("仓库A",),
            product_types=("小样",),
            page=1,
            page_size=10,
        )
        self.assertEqual(no_sales["pagination"]["total"], 1)
        self.assertIsNone(no_sales["rows"][0]["turnover_days"])
        self.assertEqual(no_sales["rows"][0]["status"], "无销量")

    def test_reconciliation_detects_mismatch(self) -> None:
        source = {
            "warehouse_records": 4,
            "stock_quantity": Decimal("15"),
            "available_stock": Decimal("11"),
            "stock_amount": Decimal("150"),
            "batch_records": 6,
            "expiring_batch_count": 3,
        }
        self.assertTrue(reconciliation_payload(source, source)["passed"])
        changed = dict(source)
        changed["available_stock"] = Decimal("12")
        self.assertFalse(reconciliation_payload(source, changed)["passed"])


if __name__ == "__main__":
    unittest.main()
