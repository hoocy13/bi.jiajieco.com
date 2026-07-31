from datetime import date, datetime
from decimal import Decimal
import unittest

from app.services.brand_inventory_flow import build_brand_inventory_flow


class BrandInventoryFlowTests(unittest.TestCase):
    def test_build_brand_inventory_flow_calculates_selected_months(self) -> None:
        source = {
            "sales": [
                {
                    "month_key": "2025-02",
                    "warehouse": "上海仓库新",
                    "product_type": "正装",
                    "sales_quantity": Decimal("30"),
                    "sales_amount": Decimal("3000"),
                    "updated_at": datetime(2026, 1, 2, 9, 0),
                }
            ],
            "inbound": [
                {
                    "month_key": "2025-02",
                    "warehouse": "上海仓库新",
                    "product_type": "正装",
                    "inbound_quantity": Decimal("50"),
                    "inbound_cost": Decimal("2500"),
                    "updated_at": datetime(2026, 1, 2, 9, 5),
                }
            ],
            "stock": [
                {
                    "snapshot_date": date(2025, 1, 31),
                    "warehouse": "上海仓库新",
                    "product_type": "正装",
                    "stock_quantity": Decimal("100"),
                    "stock_amount": Decimal("5000"),
                    "updated_at": datetime(2026, 1, 2, 9, 10),
                },
                {
                    "snapshot_date": date(2025, 2, 28),
                    "warehouse": "上海仓库新",
                    "product_type": "正装",
                    "stock_quantity": Decimal("115"),
                    "stock_amount": Decimal("5750"),
                    "updated_at": datetime(2026, 1, 2, 9, 10),
                },
                {
                    "snapshot_date": date(2025, 3, 31),
                    "warehouse": "上海仓库新",
                    "product_type": "正装",
                    "stock_quantity": Decimal("80"),
                    "stock_amount": Decimal("4000"),
                    "updated_at": datetime(2026, 1, 2, 9, 10),
                },
            ],
            "batches": [],
        }

        data = build_brand_inventory_flow(
            source,
            start_date=date(2025, 2, 1),
            end_date=date(2025, 3, 31),
            brand="资生堂",
            warehouses=("上海仓库新",),
            product_types=("正装",),
        )

        february = data["months"][0]
        self.assertEqual(len(data["months"]), 2)
        self.assertEqual(february["opening_quantity"], 100)
        self.assertEqual(february["inbound_quantity"], 50)
        self.assertEqual(february["sales_quantity"], 30)
        self.assertEqual(february["ending_quantity"], 115)
        self.assertNotIn("balance_difference", february)
        self.assertEqual(february["sell_through_rate"], 20)
        self.assertEqual(data["summary"]["ending_quantity"], 80)
        self.assertEqual(data["period"], "2025年02月—2025年03月")

    def test_build_brand_inventory_flow_applies_all_dimensions_consistently(self) -> None:
        source = {
            "sales": [
                {
                    "month_key": "2025-01",
                    "warehouse": "A仓",
                    "product_type": "正装",
                    "sales_quantity": 10,
                },
                {
                    "month_key": "2025-01",
                    "warehouse": "B仓",
                    "product_type": "小样",
                    "sales_quantity": 99,
                },
            ],
            "inbound": [],
            "stock": [],
            "batches": [],
        }

        data = build_brand_inventory_flow(
            source,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            brand="资生堂",
            warehouses=("A仓",),
            product_types=("正装",),
        )

        self.assertEqual(data["months"][0]["sales_quantity"], 10)
        self.assertEqual(data["filter_options"]["warehouses"], ["A仓", "B仓"])


if __name__ == "__main__":
    unittest.main()
