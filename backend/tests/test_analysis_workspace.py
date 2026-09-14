import unittest

from app.services.analysis_workspace import analyze_sales_workspace


class AnalysisWorkspaceTests(unittest.TestCase):
    def test_builds_comparison_brand_contribution_and_anomaly(self):
        daily = [
            {"sales_date": f"2026-06-{day:02d}", "paid_amount": 100}
            for day in range(1, 10)
        ] + [{"sales_date": "2026-06-10", "paid_amount": 1000}]
        previous = [{"sales_date": "2026-03-01", "paid_amount": 1000}]
        brands = [{"brand": "B", "paid_amount": 380}, {"brand": "A", "paid_amount": 1520}]

        result = analyze_sales_workspace(daily, previous, brands)

        self.assertEqual(result["summary"]["paid_amount"], 1900)
        self.assertEqual(result["summary"]["change_rate"], 90)
        self.assertEqual(result["brands"][0]["brand"], "A")
        self.assertEqual(result["brands"][0]["share"], 80)
        self.assertEqual(result["anomalies"][0]["date"], "2026-06-10")
        self.assertEqual(result["anomalies"][0]["direction"], "up")

    def test_zero_previous_period_has_no_misleading_rate(self):
        result = analyze_sales_workspace([], [], [])
        self.assertIsNone(result["summary"]["change_rate"])
        self.assertEqual(result["anomalies"], [])


if __name__ == "__main__":
    unittest.main()

