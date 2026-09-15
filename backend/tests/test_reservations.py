import unittest

from app.api.routers.reservations import _multi_filter, _retention_rate


class ReservationFilterTests(unittest.TestCase):
    def test_multi_filter_uses_bound_parameters(self) -> None:
        params: dict[str, object] = {}

        clause = _multi_filter(
            ("上海仓库新", "【商家仓】抖超上海仓"),
            column="h.`预留仓库`",
            prefix="warehouse",
            params=params,
        )

        self.assertEqual(clause, "AND h.`预留仓库` IN (:warehouse_0, :warehouse_1)")
        self.assertEqual(
            params,
            {
                "warehouse_0": "上海仓库新",
                "warehouse_1": "【商家仓】抖超上海仓",
            },
        )

    def test_multi_filter_omits_empty_selection(self) -> None:
        params: dict[str, object] = {}

        self.assertEqual(_multi_filter((), column="h.`状态`", prefix="status", params=params), "")
        self.assertEqual(params, {})

    def test_retention_rate_uses_remaining_over_reserved(self) -> None:
        self.assertEqual(_retention_rate(25, 200), 12.5)

    def test_retention_rate_handles_zero_reserved_quantity(self) -> None:
        self.assertIsNone(_retention_rate(0, 0))


if __name__ == "__main__":
    unittest.main()
