import unittest
from datetime import date, datetime
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
    AdsInventoryFilterOption,
    AdsInventoryProductWarehouse,
    AdsPublishBatch,
)
from app.services.inventory_ads import (
    latest_ready_inventory_batch,
    load_inventory_filter_options_from_ads,
    load_inventory_overview_from_ads,
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
        finally:
            settings.BI_QUERY_SOURCE = original_mode
            inventory_router.AdsSessionLocal = original_session
            inventory_router._inventory_cache.clear()

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
