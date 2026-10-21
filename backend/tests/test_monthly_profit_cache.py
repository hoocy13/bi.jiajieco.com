import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from app.services import monthly_profit_live as live


class MonthlyCacheTests(unittest.TestCase):
    def setUp(self):
        live._cache.clear()
        self.ods = SimpleNamespace(get_bind=lambda: SimpleNamespace(url=SimpleNamespace(
            render_as_string=lambda **kw: 'mysql://read-only-source')))
        self.price = SimpleNamespace(price=Decimal('10'), id=1)

    def test_fourth_month_does_not_evict_recently_used_month(self):
        with patch.object(live, 'current_prices', return_value={'A': self.price}), \
             patch.object(live, '_load_snapshot', return_value=('snapshot',)) as build:
            for month in ['2026-06', '2026-07', '2026-08', '2026-09', '2026-08']:
                live.live_snapshot(month, None, self.ods)
            self.assertEqual(build.call_count, 4)

    def test_same_month_concurrent_calls_share_one_build(self):
        entered, release, joined = Event(), Event(), Event()
        def build(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return ('snapshot',)
        with patch.object(live, 'current_prices', return_value={'A': self.price}), \
             patch.object(live, '_load_snapshot', side_effect=build) as loader, \
             ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(live.live_snapshot, '2026-09', None, self.ods)
            self.assertTrue(entered.wait(5))
            def second_call():
                joined.set()
                return live.live_snapshot('2026-09', None, self.ods)
            second = pool.submit(second_call)
            self.assertTrue(joined.wait(5))
            release.set()
            self.assertEqual(first.result(5), second.result(5))
            self.assertEqual(loader.call_count, 1)

    def test_changed_cost_and_failed_build_are_not_reused(self):
        with patch.object(live, 'current_prices', return_value={'A': self.price}), \
             patch.object(live, '_load_snapshot', side_effect=[RuntimeError('query failed'), ('v1',), ('v2',)]) as build:
            with self.assertRaises(RuntimeError):
                live.live_snapshot('2026-09', None, self.ods)
            self.assertEqual(live.live_snapshot('2026-09', None, self.ods), ('v1',))
            self.price.id = 2
            self.price.price = Decimal('20')
            self.assertEqual(live.live_snapshot('2026-09', None, self.ods), ('v2',))
            self.assertEqual(build.call_count, 3)

    def test_expired_entry_rebuilds(self):
        clock = [100.0]
        with patch.object(live, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(live, 'current_prices', return_value={'A': self.price}), \
             patch.object(live, '_load_snapshot', return_value=('snapshot',)) as build:
            live.live_snapshot('2026-09', None, self.ods)
            clock[0] += 301
            live.live_snapshot('2026-09', None, self.ods)
            self.assertEqual(build.call_count, 2)



if __name__ == '__main__':
    unittest.main()
