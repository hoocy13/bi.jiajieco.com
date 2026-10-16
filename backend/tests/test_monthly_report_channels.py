import copy
import json
import unittest

from app.jobs.enrich_monthly_report_channels import PROJECT_ROOT, validate_snapshot
from generate_monthly_operating_report import add_channel_analysis, month_text


class MonthlyChannelTests(unittest.TestCase):
    def setUp(self):
        self.artifact = json.loads((PROJECT_ROOT / "outputs/monthly_report_template.json").read_text(encoding="utf-8"))
        self.raw = {"sales_batch": {"data_version": "original"}, "periods": []}
        datasets = self.artifact["snapshot"]["datasets"]
        datasets["periods"] = []
        datasets["channel_structure"] = []
        for date, online, offline in [("2025-09-01", 50, 50), ("2026-08-01", 100, 0), ("2026-09-01", 120, -20)]:
            channels = [
                {"channel": "天猫店", "channel_group": "线上", "platform": "天猫", "paid_amount": online, "orders": 1, "quantity": 1},
                {"channel": "门店", "channel_group": "线下", "platform": "未设置", "paid_amount": offline, "orders": 1, "quantity": 1},
            ]
            label = month_text(date)
            self.raw["periods"].append({"start_date": date, "summary": {"paid_amount": 100, "orders": 2, "quantity": 2}, "channels": channels})
            datasets["periods"].append({"period": f"{label}（本月）", "paid_amount": 100, "orders": 2, "quantity": 2})
            datasets["channel_structure"].extend({"period": label, **row} for row in channels)

    def test_negative_records_and_zero_baseline_are_preserved(self):
        validate_snapshot(self.artifact, self.raw, "original")
        add_channel_analysis(self.artifact, self.raw)
        rows = self.artifact["snapshot"]["datasets"]["channel_sales"]
        self.assertEqual(sum(row["paid_amount"] for row in rows), 100)
        offline = next(row for row in rows if row["channel"] == "门店")
        self.assertEqual(offline["paid_amount"], -20)
        self.assertIsNone(offline["paid_amount_mom"])
        self.assertAlmostEqual(next(row for row in rows if row["channel"] == "天猫店")["paid_amount_mom"], 0.2)
        self.assertNotIn("scope_definition", [block["id"] for block in self.artifact["manifest"]["blocks"]])
        self.assertNotIn("daily_sales_trend", [chart["id"] for chart in self.artifact["manifest"]["charts"]])
        self.assertTrue(all("subtitle" not in item for item in self.artifact["manifest"]["charts"] + self.artifact["manifest"]["tables"]))

    def test_different_version_or_changed_total_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "版本"):
            validate_snapshot(self.artifact, self.raw, "newer")
        modified = copy.deepcopy(self.raw)
        modified["periods"][-1]["channels"][0]["paid_amount"] += 1
        with self.assertRaisesRegex(ValueError, "原月报"):
            validate_snapshot(self.artifact, modified, "original")

    def test_changed_classification_is_rejected_even_when_total_matches(self):
        modified = copy.deepcopy(self.raw)
        modified["periods"][-1]["channels"][0]["channel_group"] = "线下"
        with self.assertRaisesRegex(ValueError, "原月报"):
            validate_snapshot(self.artifact, modified, "original")

    def test_enriching_existing_channel_snapshot_does_not_duplicate_detail_block(self):
        add_channel_analysis(self.artifact, self.raw)
        first_rows = copy.deepcopy(self.artifact["snapshot"]["datasets"]["channel_sales"])
        add_channel_analysis(self.artifact, self.raw)
        blocks = self.artifact["manifest"]["blocks"]
        self.assertEqual(sum(block["id"] == "channel_detail_table" for block in blocks), 1)
        self.assertEqual(self.artifact["snapshot"]["datasets"]["channel_sales"], first_rows)


if __name__ == "__main__":
    unittest.main()
