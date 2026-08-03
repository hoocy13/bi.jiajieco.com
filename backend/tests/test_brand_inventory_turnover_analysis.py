from datetime import date, datetime
from decimal import Decimal
import unittest

from app.services.brand_inventory_turnover_analysis import (
    build_brand_inventory_turnover_analysis,
)


class BrandInventoryTurnoverAnalysisTests(unittest.TestCase):
    def test_uses_monthly_opening_closing_average_for_turnover_days(self) -> None:
        source = {
            "sales": [
                {
                    "month_key": month_key,
                    "warehouse": "A仓",
                    "product_type": "小样",
                    "product_code": "S",
                    "product_name": "小样S",
                    "sales_quantity": Decimal(quantity),
                }
                for month_key, quantity in (
                    ("2026-01", "1273489"),
                    ("2026-02", "432532"),
                    ("2026-03", "900166"),
                )
            ],
            "stock": [
                {
                    "snapshot_date": snapshot_date,
                    "warehouse": "A仓",
                    "product_type": "小样",
                    "product_code": "S",
                    "product_name": "小样S",
                    "stock_quantity": Decimal(quantity),
                    "stock_amount": 0,
                }
                for snapshot_date, quantity in (
                    (date(2025, 12, 31), "2492095"),
                    (date(2026, 1, 31), "1210748"),
                    (date(2026, 2, 28), "1015514"),
                    (date(2026, 3, 31), "966443"),
                )
            ],
            "batches": [
                {"snapshot_date": value, "status": "SUCCESS", "completed_at": datetime(2026, 4, 1, 8, 0)}
                for value in (
                    date(2025, 12, 31),
                    date(2026, 1, 31),
                    date(2026, 2, 28),
                    date(2026, 3, 31),
                )
            ],
        }

        data = build_brand_inventory_turnover_analysis(
            source,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            brand="资生堂",
            warehouses=("A仓",),
            product_types=("小样",),
        )

        self.assertAlmostEqual(data["summary"]["average_inventory"], 1318510.3333333333)
        self.assertEqual(data["summary"]["sales_quantity"], 2606187)
        self.assertEqual(data["summary"]["turnover_days"], 45.5)
        self.assertEqual(data["basis"], "monthly_opening_closing_average_v1")
        self.assertEqual(data["freshness"]["monthly_average_count"], 3)

    def test_builds_snapshot_average_turnover_rankings_and_channel_mix(self) -> None:
        source = {
            "sales": [
                {
                    "month_key": "2025-02",
                    "warehouse": "A仓",
                    "product_type": "正装",
                    "product_code": "A",
                    "product_name": "正装A",
                    "channel_name": "线上店",
                    "channel_category": "运营部线上渠道",
                    "channel_platform": "天猫",
                    "sales_quantity": Decimal("90"),
                    "sales_amount": Decimal("9000"),
                    "last_sale_date": datetime(2025, 2, 20, 10, 0),
                },
                {
                    "month_key": "2025-03",
                    "warehouse": "A仓",
                    "product_type": "小样",
                    "product_code": "B",
                    "product_name": "小样B",
                    "channel_name": "线下店",
                    "channel_category": "销售部渠道",
                    "channel_platform": "未设置",
                    "sales_quantity": Decimal("20"),
                    "sales_amount": Decimal("200"),
                    "last_sale_date": datetime(2025, 3, 10, 9, 0),
                },
            ],
            "stock": [
                *[
                    {
                        "snapshot_date": snapshot_date,
                        "warehouse": "A仓",
                        "product_type": "正装",
                        "product_code": "A",
                        "product_name": "正装A",
                        "stock_quantity": quantity,
                        "stock_amount": quantity * 10,
                    }
                    for snapshot_date, quantity in (
                        (date(2025, 1, 31), Decimal("90")),
                        (date(2025, 2, 28), Decimal("60")),
                        (date(2025, 3, 31), Decimal("30")),
                    )
                ],
                *[
                    {
                        "snapshot_date": snapshot_date,
                        "warehouse": "A仓",
                        "product_type": "小样",
                        "product_code": "B",
                        "product_name": "小样B",
                        "stock_quantity": quantity,
                        "stock_amount": quantity,
                    }
                    for snapshot_date, quantity in (
                        (date(2025, 1, 31), Decimal("30")),
                        (date(2025, 2, 28), Decimal("20")),
                        (date(2025, 3, 31), Decimal("10")),
                    )
                ],
                {
                    "snapshot_date": date(2025, 3, 31),
                    "warehouse": "A仓",
                    "product_type": "小样",
                    "product_code": "C",
                    "product_name": "无销售小样",
                    "stock_quantity": Decimal("15"),
                    "stock_amount": Decimal("150"),
                },
            ],
            "batches": [
                {"snapshot_date": value, "status": "SUCCESS", "completed_at": datetime(2026, 1, 1, 8, 0)}
                for value in (date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31))
            ],
        }

        data = build_brand_inventory_turnover_analysis(
            source,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 3, 31),
            brand="资生堂",
            warehouses=("A仓",),
        )

        regular = data["category_summary"][0]
        sample = data["category_summary"][1]
        self.assertEqual(regular["average_inventory"], 60)
        self.assertEqual(regular["turnover_rate"], 1.5)
        self.assertEqual(sample["average_inventory"], 23.75)
        self.assertEqual(data["waterline"][1]["total_inventory"], 55)
        self.assertEqual(data["slow_products"][0]["product_code"], "C")
        self.assertEqual(data["hot_products"][0]["product_code"], "A")
        self.assertEqual(data["channel_mix"][0]["channel_kind"], "线上")
        self.assertEqual(data["channel_mix"][0]["sales_quantity"], 90)
        self.assertFalse(data["channel_turnover"]["available"])
        self.assertTrue(data["freshness"]["snapshot_complete"])

    def test_applies_product_type_and_warehouse_filters_to_all_outputs(self) -> None:
        source = {
            "sales": [
                {"month_key": "2025-01", "warehouse": "A仓", "product_type": "正装", "product_code": "A", "product_name": "A", "sales_quantity": 10},
                {"month_key": "2025-01", "warehouse": "B仓", "product_type": "小样", "product_code": "B", "product_name": "B", "sales_quantity": 99},
            ],
            "stock": [],
            "batches": [],
        }
        data = build_brand_inventory_turnover_analysis(
            source,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            brand="资生堂",
            warehouses=("A仓",),
            product_types=("正装",),
        )

        self.assertEqual(data["summary"]["sales_quantity"], 10)
        self.assertEqual([row["product_type"] for row in data["category_summary"]], ["正装"])
        self.assertEqual(len(data["details"]), 1)
        self.assertEqual(data["details"][0]["product_code"], "A")


if __name__ == "__main__":
    unittest.main()
