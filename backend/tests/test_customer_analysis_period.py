import unittest
from datetime import date

from fastapi import HTTPException

from app.api.routers.sales import _resolve_customer_ads_period


class CustomerAnalysisPeriodTests(unittest.TestCase):
    def test_preset_range_ends_at_ads_coverage_date(self) -> None:
        params, meta = _resolve_customer_ads_period(
            "last_30",
            None,
            None,
            date(2025, 1, 1),
            date(2026, 9, 1),
        )

        self.assertEqual(params["start_date"], date(2026, 8, 3))
        self.assertEqual(params["end_date"], date(2026, 9, 1))
        self.assertEqual(meta["as_of"], "2026-09-01")

    def test_custom_range_after_ads_coverage_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as context:
            _resolve_customer_ads_period(
                "custom",
                date(2026, 8, 5),
                date(2026, 9, 3),
                date(2025, 1, 1),
                date(2026, 9, 1),
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("2026-09-01", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
