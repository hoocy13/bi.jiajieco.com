import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from fastapi import UploadFile
from openpyxl import load_workbook
import xlsxwriter

from app.api.routers import inventory_valuation


def workbook_bytes(headers, rows):
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("核心成本价")
    sheet.write_row(0, 0, headers)
    for index, row in enumerate(rows, start=1):
        sheet.write_row(index, 0, row)
    workbook.close()
    return output.getvalue()


class CoreCostImportTest(unittest.IsolatedAsyncioTestCase):
    async def preview(self, content):
        file = UploadFile(file=BytesIO(content), filename="核心成本价.xlsx")
        return (await inventory_valuation.import_preview(file))["data"]

    async def test_export_can_be_imported_with_four_columns(self):
        price = {
            "product_code": "SKU-1", "product_name": "Test", "price": 12.5,
            "effective_date": "2026-10-08", "operator": "operator-1",
            "source": "import", "created_at": "2026-10-08T10:00:00",
        }
        with patch.object(inventory_valuation, "list_prices", return_value={"data": [price]}):
            exported = inventory_valuation.export_prices(keyword="", admin=None)
        sheet = load_workbook(BytesIO(exported.body), read_only=True).active
        self.assertEqual([cell.value for cell in sheet[1]], ["货品编号", "货品名称", "品牌", "核心成本价"])
        preview = await self.preview(exported.body)
        self.assertEqual(preview["errors"], [])
        self.assertEqual(preview["rows"], [{
            "product_code": "SKU-1", "product_name": "Test", "price": "12.5",
            "effective_date": date.today().isoformat(), "brand": "",
        }])

    async def test_four_column_file_defaults_to_today(self):
        content = workbook_bytes(
            ["货品编号", "货品名称", "品牌", "核心成本价"],
            [["SKU-2", "Test", "品牌甲", 9.5]],
        )
        preview = await self.preview(content)
        self.assertEqual(preview["rows"][0]["effective_date"], date.today().isoformat())
        self.assertEqual(preview["rows"][0]["brand"], "品牌甲")

    async def test_invalid_price_is_reported(self):
        content = workbook_bytes(
            ["货品编号", "货品名称", "品牌", "核心成本价"],
            [["SKU-3", "Invalid", "品牌甲", "not-a-price"]],
        )
        preview = await self.preview(content)
        self.assertEqual(preview["rows"], [])
        self.assertEqual(preview["errors"], ["第 2 行核心成本价无效"])

    async def test_brand_filter_uses_inventory_brand(self):
        class Revision:
            def __init__(self, code):
                self.id = 1
                self.product_code = code
                self.product_name = code
                self.price = 12.5
                self.effective_date = date(2026, 10, 8)
                self.source = "import"
                self.restored_from_id = None
                self.operator = "tester"
                self.created_at = None

        revisions = {code: Revision(code) for code in ("SKU-1", "SKU-2")}
        with patch.object(inventory_valuation, "current_prices", return_value=revisions), \
             patch.object(inventory_valuation, "price_brands", return_value={"SKU-1": "品牌甲", "SKU-2": "品牌乙"}):
            rows = inventory_valuation.list_prices(keyword="", brand=["品牌甲"], ods=None, admin=None)["data"]
        self.assertEqual([(row["product_code"], row["brand"]) for row in rows], [("SKU-1", "品牌甲")])

    async def test_deleted_price_stays_out_of_current_prices_until_restored(self):
        class Revision:
            def __init__(self, revision_id, source, price):
                self.id = revision_id
                self.product_code = "SKU-1"
                self.product_name = "Test"
                self.price = Decimal(price)
                self.effective_date = date.today()
                self.source = source

        class Query:
            def __init__(self, rows):
                self.rows = rows

            def filter(self, *_):
                return self

            def order_by(self, *_):
                return self

            def all(self):
                return self.rows

        class Db:
            def __init__(self, rows):
                self.rows = rows

            def query(self, *_):
                return Query(self.rows)

        old = Revision(1, "import", "12.50")
        deleted = Revision(2, "delete", "12.50")
        restored = Revision(3, "restore", "12.50")
        self.assertEqual(inventory_valuation.price_states(Db([deleted, old])), ({}, {"SKU-1": deleted}))
        self.assertEqual(inventory_valuation.price_states(Db([restored, deleted, old])), ({"SKU-1": restored}, {}))


if __name__ == "__main__":
    unittest.main()
