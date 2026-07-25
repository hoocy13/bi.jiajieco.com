import unittest
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal

from fastapi import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.api.routers.sales as sales_router
from app.core.config import settings
from app.db.ads import ensure_separate_ads_database
from app.jobs.build_sales_ads import (
    SalesSummary,
    new_data_version,
    reconciliation_payload,
    summaries_match,
)
from app.models.ads import (
    AdsBase,
    AdsPublishBatch,
    AdsSalesDaily,
    AdsSalesDailyBrandProduct,
    AdsSalesDailyBrandScope,
    AdsSalesDailyChannel,
    AdsSalesDailyProduct,
    AdsSalesDetailDaily,
    AdsSalesDetailDailyChannel,
    AdsSalesDetailDailyScope,
)
from app.services.sales_ads import (
    compare_sales_overviews,
    latest_ready_sales_batch,
    load_sales_brand_analysis_from_ads,
    load_sales_channel_analysis_from_ads,
    load_sales_overview_from_ads,
    load_sales_product_rank_from_ads,
)


class AdsDatabaseSafetyTests(unittest.TestCase):
    def test_rejects_same_mysql_database(self) -> None:
        with self.assertRaises(RuntimeError):
            ensure_separate_ads_database(
                "mysql+pymysql://reader:secret@db.example:3306/ods",
                "mysql+pymysql://writer:secret@db.example:3306/ods",
            )

    def test_allows_separate_mysql_database_on_same_server(self) -> None:
        ensure_separate_ads_database(
            "mysql+pymysql://reader:secret@db.example:3306/ods",
            "mysql+pymysql://writer:secret@db.example:3306/bi_ads",
        )


class AdsSchemaTests(unittest.TestCase):
    def test_schema_can_be_created(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            AdsBase.metadata.create_all(engine)
            self.assertEqual(
                set(AdsBase.metadata.tables),
                {
                    "ads_publish_batch",
                    "ads_sales_daily",
                    "ads_sales_daily_brand_product",
                    "ads_sales_daily_brand_scope",
                    "ads_sales_daily_channel",
                    "ads_sales_daily_product",
                    "ads_sales_detail_daily",
                    "ads_sales_detail_daily_channel",
                    "ads_sales_detail_daily_scope",
                },
            )
        finally:
            engine.dispose()


class SalesReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = SalesSummary(
            orders=12,
            paid_amount=Decimal("1234.560000"),
            quantity=Decimal("45.0000"),
        )

    def test_matching_summaries_pass(self) -> None:
        self.assertTrue(summaries_match(self.summary, self.summary))
        payload = reconciliation_payload(
            self.summary,
            self.summary,
            SalesSummary(
                orders=0,
                paid_amount=self.summary.paid_amount,
                quantity=self.summary.quantity,
            ),
        )
        self.assertTrue(payload["passed"])

    def test_order_difference_fails_daily_reconciliation(self) -> None:
        different = SalesSummary(
            orders=13,
            paid_amount=self.summary.paid_amount,
            quantity=self.summary.quantity,
        )
        payload = reconciliation_payload(
            self.summary,
            different,
            SalesSummary(
                orders=0,
                paid_amount=self.summary.paid_amount,
                quantity=self.summary.quantity,
            ),
        )
        self.assertFalse(payload["passed"])
        self.assertFalse(payload["daily_matches"])

    def test_data_version_contains_source_date(self) -> None:
        version = new_data_version(date(2026, 7, 25))
        self.assertTrue(version.startswith("sales-2026-07-25-"))
        self.assertLessEqual(len(version), 64)

    def test_product_rank_reconciliation_checks_both_aggregates(self) -> None:
        payload = reconciliation_payload(
            self.summary,
            self.summary,
            SalesSummary(
                orders=0,
                paid_amount=self.summary.paid_amount,
                quantity=self.summary.quantity,
            ),
            self.summary,
            self.summary,
            SalesSummary(
                orders=99,
                paid_amount=self.summary.paid_amount,
                quantity=self.summary.quantity,
            ),
        )
        self.assertTrue(payload["passed"])
        self.assertTrue(payload["product_rank"]["detail_daily_matches"])
        self.assertTrue(payload["product_rank"]["product_amount_quantity_matches"])


class SalesAdsReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        AdsBase.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        batch = AdsPublishBatch(
            data_version="sales-test-ready",
            dataset="sales_daily",
            status="ready",
            source_start_date=date(2026, 7, 1),
            source_end_date=date(2026, 7, 2),
            created_at=datetime(2026, 7, 2, 1, 0),
            finished_at=datetime(2026, 7, 2, 1, 1),
            published_at=datetime(2026, 7, 2, 1, 1),
        )
        self.db.add(batch)
        self.db.add_all(
            [
                AdsSalesDaily(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    orders=2,
                    paid_amount=Decimal("100.000000"),
                    quantity=Decimal("5.0000"),
                ),
                AdsSalesDaily(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    orders=3,
                    paid_amount=Decimal("50.000000"),
                    quantity=Decimal("-1.0000"),
                ),
                AdsSalesDailyChannel(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    channel="渠道A",
                    orders=1,
                    paid_amount=Decimal("80.000000"),
                    quantity=Decimal("4.0000"),
                ),
                AdsSalesDailyChannel(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    channel="渠道B",
                    orders=1,
                    paid_amount=Decimal("20.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyChannel(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    channel="渠道A",
                    orders=3,
                    paid_amount=Decimal("50.000000"),
                    quantity=Decimal("-1.0000"),
                ),
                AdsSalesDetailDaily(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    orders=2,
                    paid_amount=Decimal("90.000000"),
                    quantity=Decimal("3.0000"),
                ),
                AdsSalesDetailDaily(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    orders=2,
                    paid_amount=Decimal("60.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDetailDailyChannel(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    channel="渠道A",
                    orders=2,
                    paid_amount=Decimal("90.000000"),
                    quantity=Decimal("3.0000"),
                ),
                AdsSalesDetailDailyChannel(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    channel="渠道A",
                    orders=2,
                    paid_amount=Decimal("60.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDailyProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product="商品A",
                    orders=2,
                    paid_amount=Decimal("70.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDailyProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product="商品B",
                    orders=1,
                    paid_amount=Decimal("20.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product="商品A",
                    orders=1,
                    paid_amount=Decimal("10.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product="商品B",
                    orders=1,
                    paid_amount=Decimal("50.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDetailDailyScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product_type_scope="all",
                    orders=2,
                    paid_amount=Decimal("90.000000"),
                    quantity=Decimal("3.0000"),
                ),
                AdsSalesDetailDailyScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product_type_scope="all",
                    orders=2,
                    paid_amount=Decimal("60.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDetailDailyScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product_type_scope="full_size",
                    orders=2,
                    paid_amount=Decimal("70.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDetailDailyScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product_type_scope="full_size",
                    orders=1,
                    paid_amount=Decimal("10.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product_type_scope="all",
                    brand="品牌A",
                    orders=2,
                    paid_amount=Decimal("70.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product_type_scope="all",
                    brand="品牌B",
                    orders=1,
                    paid_amount=Decimal("20.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product_type_scope="all",
                    brand="品牌A",
                    orders=1,
                    paid_amount=Decimal("10.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product_type_scope="all",
                    brand="品牌B",
                    orders=1,
                    paid_amount=Decimal("50.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    product_type_scope="full_size",
                    brand="品牌A",
                    orders=2,
                    paid_amount=Decimal("70.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDailyBrandScope(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    product_type_scope="full_size",
                    brand="品牌A",
                    orders=1,
                    paid_amount=Decimal("10.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    brand="品牌A",
                    product_type="正装",
                    product="商品A",
                    orders=2,
                    paid_amount=Decimal("70.000000"),
                    quantity=Decimal("2.0000"),
                ),
                AdsSalesDailyBrandProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 1),
                    brand="品牌B",
                    product_type="小样",
                    product="商品B",
                    orders=1,
                    paid_amount=Decimal("20.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    brand="品牌A",
                    product_type="正装",
                    product="商品A",
                    orders=1,
                    paid_amount=Decimal("10.000000"),
                    quantity=Decimal("1.0000"),
                ),
                AdsSalesDailyBrandProduct(
                    data_version=batch.data_version,
                    sales_date=date(2026, 7, 2),
                    brand="品牌B",
                    product_type="小样",
                    product="商品B",
                    orders=1,
                    paid_amount=Decimal("50.000000"),
                    quantity=Decimal("1.0000"),
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_loads_overview_from_latest_ready_version(self) -> None:
        batch = latest_ready_sales_batch(self.db)
        data = load_sales_overview_from_ads(
            self.db,
            batch,
            {
                "as_of": "2026-07-02",
                "period": "自定义",
                "range": "custom",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        self.assertEqual(data["metrics"]["orders"], 5)
        self.assertEqual(data["metrics"]["quantity"], 4)
        self.assertEqual(data["metrics"]["paid_amount"], 150)
        self.assertEqual([row["channel"] for row in data["channels"]], ["渠道A", "渠道B"])
        self.assertEqual(data["channels"][0]["paid_amount"], 130)

    def test_comparison_reports_metric_difference(self) -> None:
        batch = latest_ready_sales_batch(self.db)
        data = load_sales_overview_from_ads(
            self.db,
            batch,
            {
                "as_of": "2026-07-02",
                "period": "自定义",
                "range": "custom",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
        )
        self.assertEqual(compare_sales_overviews(data, data), [])
        changed = deepcopy(data)
        changed["metrics"]["orders"] += 1
        differences = compare_sales_overviews(data, changed)
        self.assertIn("metrics.orders", [difference.path for difference in differences])

    def test_loads_product_rank_and_keyword_from_ads(self) -> None:
        batch = latest_ready_sales_batch(self.db)
        meta = {
            "as_of": "2026-07-02",
            "period": "自定义",
            "range": "custom",
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
        }
        data = load_sales_product_rank_from_ads(self.db, batch, meta, limit=10)
        self.assertEqual(data["summary"]["paid_amount"], 150)
        self.assertEqual(data["summary"]["quantity"], 4)
        self.assertEqual(data["rank_summary"]["orders"], 4)
        self.assertEqual(data["rank_summary"]["quantity"], 5)
        self.assertEqual([row["product"] for row in data["rows"]], ["商品A", "商品B"])
        self.assertEqual([row["product"] for row in data["quantity_rows"]], ["商品A", "商品B"])

        filtered = load_sales_product_rank_from_ads(
            self.db,
            batch,
            meta,
            limit=10,
            keyword="商品A",
            exact_filtered_orders=2,
        )
        self.assertEqual(filtered["rank_summary"]["orders"], 2)
        self.assertEqual(filtered["rank_summary"]["paid_amount"], 80)
        self.assertEqual([row["product"] for row in filtered["rows"]], ["商品A"])

    def test_loads_brand_analysis_and_product_type_from_ads(self) -> None:
        batch = latest_ready_sales_batch(self.db)
        meta = {
            "as_of": "2026-07-02",
            "period": "自定义",
            "range": "custom",
            "start_date": "2026-07-01",
            "end_date": "2026-07-02",
        }
        data = load_sales_brand_analysis_from_ads(
            self.db,
            batch,
            meta,
            limit=10,
            product_types=[],
        )
        self.assertEqual(data["summary"]["quantity"], 4)
        self.assertEqual(data["rank_summary"]["quantity"], 5)
        self.assertEqual([row["brand"] for row in data["rows"]], ["品牌A", "品牌B"])
        self.assertEqual(data["rows"][0]["product_count"], 1)

        filtered = load_sales_brand_analysis_from_ads(
            self.db,
            batch,
            meta,
            limit=10,
            product_types=["正装"],
        )
        self.assertEqual(filtered["summary"]["paid_amount"], 80)
        self.assertEqual(filtered["summary"]["orders"], 3)
        self.assertEqual([row["brand"] for row in filtered["rows"]], ["品牌A"])

    def test_loads_channel_analysis_with_live_dimensions(self) -> None:
        batch = latest_ready_sales_batch(self.db)
        data = load_sales_channel_analysis_from_ads(
            self.db,
            batch,
            {
                "as_of": "2026-07-02",
                "period": "自定义",
                "range": "custom",
                "start_date": "2026-07-01",
                "end_date": "2026-07-02",
            },
            dimension_rows=[
                {
                    "channel_code": "A",
                    "channel_name": "渠道A",
                    "category": "运营部线上渠道",
                    "channel_type": "直营网店",
                    "platform": "平台A",
                    "owner": "负责人A",
                    "authorized": 1,
                },
                {
                    "channel_code": "B",
                    "channel_name": "渠道B",
                    "category": "销售部渠道",
                    "channel_type": "线下门店",
                    "platform": "未设置",
                    "owner": "负责人B",
                    "authorized": 0,
                },
            ],
            filter_option_rows=[
                {"channel_type": "直营网店", "platform": "平台A", "channel_name": "渠道A"},
                {"channel_type": "线下门店", "platform": "未设置", "channel_name": "渠道B"},
            ],
            include_unmatched=True,
        )
        self.assertEqual(data["summary"]["paid_amount"], 150)
        self.assertEqual(data["summary"]["orders"], 4)
        self.assertEqual([row["channel_name"] for row in data["rows"]], ["渠道A", "渠道B"])
        self.assertTrue(data["rows"][0]["is_online"])
        self.assertEqual(data["channel_summary"]["active_channels"], 1)
        self.assertEqual(data["filter_options"]["platforms"], ["平台A"])

    def test_ads_query_mode_does_not_require_ods_session(self) -> None:
        original_mode = settings.BI_QUERY_SOURCE
        original_ads_session = sales_router.AdsSessionLocal
        try:
            settings.BI_QUERY_SOURCE = "ads"
            sales_router.AdsSessionLocal = sessionmaker(bind=self.engine)
            sales_router._sales_cache.clear()
            response = Response()
            payload = sales_router.sales_overview(
                response=response,
                range="custom",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                current_user=None,
                db=None,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(payload["data"]["metrics"]["paid_amount"], 150)
        finally:
            settings.BI_QUERY_SOURCE = original_mode
            sales_router.AdsSessionLocal = original_ads_session
            sales_router._sales_cache.clear()

    def test_product_rank_uses_ads_in_ads_mode(self) -> None:
        original_mode = settings.BI_QUERY_SOURCE
        original_ads_session = sales_router.AdsSessionLocal
        try:
            settings.BI_QUERY_SOURCE = "ads"
            sales_router.AdsSessionLocal = sessionmaker(bind=self.engine)
            sales_router._sales_cache.clear()
            response = Response()
            payload = sales_router.sales_product_rank(
                response=response,
                range="custom",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                limit=10,
                keyword=None,
                current_user=None,
                db=self.db,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(payload["data"]["rank_summary"]["paid_amount"], 150)
        finally:
            settings.BI_QUERY_SOURCE = original_mode
            sales_router.AdsSessionLocal = original_ads_session
            sales_router._sales_cache.clear()

    def test_brand_analysis_uses_ads_in_ads_mode(self) -> None:
        original_mode = settings.BI_QUERY_SOURCE
        original_ads_session = sales_router.AdsSessionLocal
        try:
            settings.BI_QUERY_SOURCE = "ads"
            sales_router.AdsSessionLocal = sessionmaker(bind=self.engine)
            sales_router._sales_cache.clear()
            response = Response()
            payload = sales_router.sales_brand_analysis(
                response=response,
                range="custom",
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 2),
                limit=10,
                keyword=None,
                product_type=["正装"],
                current_user=None,
                db=self.db,
            )
            self.assertEqual(response.headers["x-bi-response-source"], "ads")
            self.assertEqual(payload["data"]["summary"]["paid_amount"], 80)
        finally:
            settings.BI_QUERY_SOURCE = original_mode
            sales_router.AdsSessionLocal = original_ads_session
            sales_router._sales_cache.clear()


if __name__ == "__main__":
    unittest.main()
