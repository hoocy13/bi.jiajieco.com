from datetime import date, datetime, timedelta
from decimal import Decimal
import unittest

from app.services.slow_moving_period_analysis import build_slow_moving_period_analysis


class SlowMovingPeriodAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = date(2026, 7, 31)
        self.previous = date(2026, 6, 30)
        self.source = {
            "stock": [
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "A",
                    "product_name": "无销售商品",
                    "brand": "品牌A",
                    "barcode": "A-1",
                    "stock_quantity": Decimal("100"),
                    "stock_amount": Decimal("1000"),
                    "updated_at": datetime(2026, 8, 1, 3, 0),
                },
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "B",
                    "product_name": "严重滞销商品",
                    "brand": "品牌B",
                    "barcode": "B-1",
                    "stock_quantity": Decimal("300"),
                    "stock_amount": Decimal("3000"),
                },
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "小样",
                    "product_code": "C",
                    "product_name": "正常关注商品",
                    "brand": "品牌C",
                    "barcode": "C-1",
                    "stock_quantity": Decimal("60"),
                    "stock_amount": Decimal("600"),
                },
                {
                    "snapshot_date": self.previous,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "A",
                    "product_name": "无销售商品",
                    "brand": "品牌A",
                    "stock_quantity": Decimal("120"),
                    "stock_amount": Decimal("1200"),
                },
            ],
            "sales": [
                {
                    "sales_date": date(2026, 7, 10),
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "B",
                    "product_name": "严重滞销商品",
                    "brand": "品牌B",
                    "sales_quantity": Decimal("100"),
                },
                {
                    "sales_date": date(2026, 7, 15),
                    "warehouse": "上海仓",
                    "product_type": "小样",
                    "product_code": "C",
                    "product_name": "正常关注商品",
                    "brand": "品牌C",
                    "sales_quantity": Decimal("90"),
                },
            ],
        }

    def test_builds_risk_summary_and_period_rows(self) -> None:
        result = build_slow_moving_period_analysis(
            self.source,
            snapshot_date=self.snapshot,
            trend_dates=(self.previous, self.snapshot),
            period_days=90,
            risk_scope="slow_all",
            page=1,
            page_size=50,
        )

        self.assertEqual(result["summary"]["stock_sku_count"], 3)
        self.assertEqual(result["summary"]["slow_sku_count"], 2)
        self.assertEqual(result["summary"]["stock_quantity"], 460.0)
        self.assertEqual(result["summary"]["slow_stock_quantity"], 400.0)
        self.assertAlmostEqual(result["summary"]["slow_stock_share"], 400 / 460 * 100)
        self.assertNotIn("stock_amount", result["summary"])
        self.assertEqual(result["pagination"]["total"], 2)
        self.assertEqual([row["risk_code"] for row in result["rows"]], ["critical", "no_sales"])
        self.assertNotIn("stock_amount", result["rows"][0])
        self.assertEqual(result["rows"][0]["estimated_days"], 270.0)
        self.assertEqual(len(result["trend"]), 2)
        self.assertEqual(result["trend"][1]["slow_stock_quantity"], 400.0)

    def test_can_filter_watch_and_sort_sales(self) -> None:
        result = build_slow_moving_period_analysis(
            self.source,
            snapshot_date=self.snapshot,
            trend_dates=(self.snapshot,),
            period_days=90,
            risk_scope="watch",
            page=1,
            page_size=50,
            sort_by="period_sales",
            sort_order="desc",
        )

        self.assertEqual(result["pagination"]["total"], 1)
        self.assertEqual(result["rows"][0]["product_code"], "C")
        self.assertAlmostEqual(result["rows"][0]["ending_stock_ratio"], 40.0)

    def test_can_filter_retention_rate_band(self) -> None:
        result = build_slow_moving_period_analysis(
            self.source,
            snapshot_date=self.snapshot,
            trend_dates=(self.snapshot,),
            period_days=90,
            risk_scope="all",
            retention_scope="ge90",
            page=1,
            page_size=50,
        )

        self.assertEqual(result["retention_scope"], "ge90")
        self.assertEqual([row["product_code"] for row in result["rows"]], ["A"])

    def test_matches_sales_by_product_code_when_brand_or_type_text_differs(self) -> None:
        source = {
            "stock": [{
                "snapshot_date": self.snapshot,
                "warehouse": "上海仓",
                "product_type": "正装",
                "product_code": "SKU-001",
                "product_name": "测试商品",
                "brand": "品牌A",
                "stock_quantity": Decimal("60"),
            }],
            "sales": [{
                "sales_date": date(2026, 7, 15),
                "warehouse": "上海仓",
                "product_type": "未归类",
                "product_code": "SKU-001",
                "product_name": "测试商品新名称",
                "brand": "品牌A（补全）",
                "sales_quantity": Decimal("40"),
            }],
        }

        result = build_slow_moving_period_analysis(
            source,
            snapshot_date=self.snapshot,
            trend_dates=(self.snapshot,),
            period_days=90,
            risk_scope="all",
        )

        self.assertEqual(result["rows"][0]["period_sales"], 40.0)
        self.assertAlmostEqual(result["rows"][0]["ending_stock_ratio"], 60.0)

    def test_separates_true_no_sales_from_return_anomaly(self) -> None:
        source = {
            "stock": [
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "NO-SALES",
                    "product_name": "真无动销商品",
                    "brand": "品牌A",
                    "stock_quantity": Decimal("30"),
                },
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "RETURNS",
                    "product_name": "净退货商品",
                    "brand": "品牌B",
                    "stock_quantity": Decimal("80"),
                },
            ],
            "sales": [
                {
                    "snapshot_date": self.snapshot,
                    "product_code": "RETURNS",
                    "product_name": "净退货商品",
                    "brand": "品牌B",
                    "sales_quantity": Decimal("-5"),
                    "positive_sales_quantity": Decimal("10"),
                    "return_quantity": Decimal("15"),
                    "last_sale_at": datetime(2026, 7, 20, 12, 0),
                }
            ],
        }

        result = build_slow_moving_period_analysis(
            source,
            snapshot_date=self.snapshot,
            trend_dates=(),
            period_days=90,
            risk_scope="slow_all",
            basis="current_available_stock",
        )

        by_code = {row["product_code"]: row for row in result["rows"]}
        self.assertEqual(by_code["NO-SALES"]["risk_code"], "no_sales")
        self.assertEqual(by_code["RETURNS"]["risk_code"], "return_anomaly")
        self.assertEqual(by_code["RETURNS"]["positive_sales"], 10.0)
        self.assertEqual(by_code["RETURNS"]["return_quantity"], 15.0)
        self.assertEqual(result["summary"]["return_anomaly_stock_quantity"], 80.0)
        self.assertEqual(result["basis"], "current_available_stock")

    def test_current_summary_is_not_overwritten_by_historical_trend(self) -> None:
        result = build_slow_moving_period_analysis(
            self.source,
            snapshot_date=self.snapshot,
            trend_dates=(self.previous,),
            period_days=90,
            risk_scope="slow_all",
            basis="current_available_stock",
        )

        self.assertEqual(result["summary"]["slow_stock_quantity"], 400.0)
        self.assertEqual(result["trend"][0]["slow_stock_quantity"], 120.0)

    def test_current_view_can_report_sales_through_previous_ready_day(self) -> None:
        sales_end = self.snapshot - timedelta(days=1)
        result = build_slow_moving_period_analysis(
            self.source,
            snapshot_date=self.snapshot,
            trend_dates=(self.previous,),
            period_days=90,
            basis="current_available_stock",
            sales_end_date=sales_end,
        )

        self.assertEqual(result["snapshot_date"], self.snapshot.isoformat())
        self.assertEqual(result["sales_end_date"], sales_end.isoformat())
        self.assertEqual(
            result["period_start"],
            (sales_end - timedelta(days=89)).isoformat(),
        )

    def test_detail_exposes_inventory_and_available_stock_separately(self) -> None:
        source = {
            "stock": [
                {
                    "snapshot_date": self.snapshot,
                    "warehouse": "上海仓",
                    "product_type": "正装",
                    "product_code": "A",
                    "product_name": "商品A",
                    "brand": "品牌A",
                    "inventory_stock_quantity": Decimal("150"),
                    "stock_quantity": Decimal("120"),
                }
            ],
            "sales": [],
        }

        result = build_slow_moving_period_analysis(
            source,
            snapshot_date=self.snapshot,
            trend_dates=(),
            period_days=90,
            basis="current_available_stock",
        )

        self.assertEqual(result["rows"][0]["inventory_stock"], 150.0)
        self.assertEqual(result["rows"][0]["stock"], 120.0)


if __name__ == "__main__":
    unittest.main()
