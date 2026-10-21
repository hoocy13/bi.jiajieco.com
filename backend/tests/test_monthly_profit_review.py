import unittest
from datetime import date
from fastapi import HTTPException
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.deps import get_current_user
from app.api.routers.sales_profit import router
from app.db.session import get_db
from app.db.ods import get_ods_db
from app.services.monthly_profit_review import review_data, summarize
from app.services.monthly_profit_live import month_period


class ReviewTests(unittest.TestCase):
    def test_monthly_endpoint_works_with_production_database_and_filters(self):
        app = FastAPI()
        app.include_router(router, prefix='/api/v1')
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='sales.profit.view')]))
        app.dependency_overrides[get_db] = lambda: 'admin-session'
        app.dependency_overrides[get_ods_db] = lambda: 'ods-session'
        production_engine = SimpleNamespace(url=SimpleNamespace(
            database='/app/data/bi_admin.db', get_backend_name=lambda: 'sqlite'))
        with patch('app.db.session.engine', production_engine), \
             patch('app.services.monthly_profit_live.live_snapshot', return_value=self.snapshot()) as load, \
             TestClient(app) as client:
            response = client.get('/api/v1/sales/profit-analysis/monthly-review')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(load.call_args.args[1:], ('admin-session', 'ods-session'))
            response = client.get('/api/v1/sales/profit-analysis/monthly-review', params={
                'month': '2026-09', 'kind': '正装', 'channel': 'X', 'view': 'product'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(load.call_args.args, ('2026-09', 'admin-session', 'ods-session'))
            self.assertEqual(response.json()['data']['filtered_summary']['profit'], -20)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            role=SimpleNamespace(is_active=True, permissions=[]))
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/sales/profit-analysis/monthly-review').status_code, 403)

    def snapshot(self):
        rows = [dict(bucket='规则可计算订单', code='a', kind='正装', channel='X', quantity=2, amount=80),
                dict(bucket='待核订单', code='a', kind='正装', channel='X', quantity=-1, amount=0),
                dict(bucket='缺成本订单', code='a', kind='正装', channel='Y', quantity=1, amount=40)]
        report = dict(eligible_positive_sales_share='50', counts=[], buckets={})
        pending = [dict(order_no='R1', channel='X', amount=0, quantity=-1,
                        zero_return=1, zero_dispatch=0, irregular=0, missing_cost=0)]
        return ('frozen', report, rows, pending, {'a': {'price': '50'}}, {'a': 'Product A'})

    def test_filters_never_promote_isolated_order_into_profit(self):
        with patch('app.services.monthly_profit_review.load_snapshot', return_value=self.snapshot()):
            result = review_data(channel='X', kind='正装', view='product')
            self.assertEqual(result['filtered_summary']['profit'], -20)
            self.assertEqual(result['summary']['profit'], -20)
            pending = review_data(channel='X', bucket='待核订单', view='product')
            self.assertIsNone(pending['rows'][0]['profit'])

    def test_pending_reason_and_pagination_do_not_disclose_profit(self):
        with patch('app.services.monthly_profit_review.load_snapshot', return_value=self.snapshot()):
            result = review_data(view='orders', bucket='待核订单')
            self.assertEqual(result['total'], 1)
            self.assertIn('退货', result['rows'][0]['reason'])
            self.assertIsNone(result['rows'][0]['profit'])
            self.assertEqual(review_data(view='orders', bucket='待核订单', page=2)['rows'], [])

    def test_missing_cost_never_becomes_zero_cost_profit(self):
        rows = [dict(code='missing', amount=200, quantity=1)]
        self.assertIsNone(summarize(rows, {}, eligible=True)['profit'])

    def test_month_boundaries_include_today_without_future_days(self):
        self.assertEqual(month_period('2026-10', date(2026, 10, 21)),
                         (date(2026, 10, 1), date(2026, 10, 22)))
        self.assertEqual(month_period('2026-09', date(2026, 10, 21)),
                         (date(2026, 9, 1), date(2026, 10, 1)))
        with self.assertRaises(HTTPException):
            month_period('2026-11', date(2026, 10, 21))

    def test_top_cards_follow_channel_filters_without_reclassification(self):
        with patch('app.services.monthly_profit_review.load_snapshot', return_value=self.snapshot()):
            result = review_data(channel='Y')
            self.assertEqual(result['summary']['net_sales'], 0)
            missing = next(b for b in result['buckets'] if b['name'] == '缺成本订单')
            self.assertEqual(missing['net_sales'], 40)

    def test_net_sales_share_uses_same_scope_and_all_buckets(self):
        with patch('app.services.monthly_profit_review.load_snapshot', return_value=self.snapshot()):
            result = review_data()
            self.assertEqual(result['sales_coverage']['eligible_net_sales'], 80)
            self.assertEqual(result['sales_coverage']['total_net_sales'], 120)
            self.assertAlmostEqual(result['sales_coverage']['net_share'], 80 / 120 * 100)
            self.assertEqual(result['repair_summary']['pending_reasons'][0]['orders'], 1)


if __name__ == '__main__':
    unittest.main()
