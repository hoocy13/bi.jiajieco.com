from datetime import date, datetime
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


if __name__ == "__main__":
    unittest.main()
