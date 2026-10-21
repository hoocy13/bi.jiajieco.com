import unittest
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from sqlalchemy import text
from fastapi import Response
from app.api.routers.reservations import reservation_analysis
from app.services import reservation_cache as cache

from app.api.routers.reservations import _multi_filter, _retention_rate


class ReservationFilterTests(unittest.TestCase):
    def setUp(self):
        cache._cache.clear()

    def test_page_changes_reuse_aggregates_but_not_detail_rows(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = [{'quantity': 2}]
        reads = cache.ReservationReads(db, {'updated_at': 'v1'})
        aggregate = text('SELECT SUM(quantity) FROM details WHERE brand=:brand')
        detail = text('SELECT quantity FROM details WHERE brand=:brand LIMIT :limit OFFSET :offset')
        for page in (0, 20):
            reads.execute(aggregate, {'brand': 'A'}).mappings().all()
            reads.execute(detail, {'brand': 'A', 'limit': 20, 'offset': page}).mappings().all()
        self.assertEqual(db.execute.call_count, 3)
        reads.execute(aggregate, {'brand': 'B'}).mappings().all()
        self.assertEqual(db.execute.call_count, 4)
        cache.ReservationReads(db, {'updated_at': 'v2'}).execute(aggregate, {'brand': 'A'}).mappings().all()
        self.assertEqual(db.execute.call_count, 5)

    def test_cache_expiry_copy_and_budget(self):
        load = MagicMock(return_value=[{'quantity': -3}])
        with patch.object(cache, 'monotonic', return_value=0):
            cache.cached(('a',), load)[0]['quantity'] = 999
            self.assertEqual(cache.cached(('a',), load)[0]['quantity'], -3)
        with patch.object(cache, 'monotonic', return_value=61):
            cache.cached(('a',), load)
        self.assertEqual(load.call_count, 2)
        with patch.object(cache, 'MAX_ITEMS', 2):
            for key in range(5): cache.cached((key,), lambda: [key])
        self.assertLessEqual(len(cache._cache), 2)
        with patch.object(cache, 'MAX_ITEM_BYTES', 1):
            large = MagicMock(return_value=['larger'])
            cache.cached(('large',), large)
            cache.cached(('large',), large)
            self.assertEqual(large.call_count, 2)

    def test_same_query_concurrency_loads_once(self):
        entered, release = Event(), Event()
        def load():
            entered.set()
            release.wait(2)
            return [1]
        loader = MagicMock(side_effect=load)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.cached, ('concurrent',), loader)
            self.assertTrue(entered.wait(1))
            second = pool.submit(cache.cached, ('concurrent',), loader)
            release.set()
            self.assertEqual(first.result(), second.result())
        loader.assert_called_once()

    def test_detail_view_does_not_compute_charts(self):
        db = MagicMock()
        db.execute.return_value.mappings.return_value.all.return_value = []
        db.execute.return_value.mappings.return_value.one.return_value = dict.fromkeys(
            ['min_date', 'max_date', 'updated_at', 'detail_updated_at', 'header_count', 'detail_count',
             'order_count', 'active_order_count', 'sku_count', 'reserved_quantity',
             'remaining_quantity', 'used_quantity', 'released_quantity'], 0)
        db.execute.return_value.scalar_one.return_value = 0
        result = reservation_analysis(response=Response(), start_date=None, end_date=None,
            status=None, warehouse=None, brand=None, product_type=None, department=None,
            applicant=None, keyword=None, page=1, page_size=20, current_user=None, db=db, view='details')
        self.assertEqual(result['data']['statuses'], [])
        self.assertTrue(all('GROUP BY' not in str(call.args[0]) for call in db.execute.call_args_list))

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
