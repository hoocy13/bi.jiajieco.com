import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routers import ai_decisions as api
from app.api.deps import get_current_user, require_permission
from app.services import decision_summary as jobs, decision_sales
from app.models.ads import AdsPublishBatch, AdsSalesDaily, AdsSalesDailyChannel


class DecisionTests(unittest.TestCase):
    def setUp(self):
        api._cache.clear()

    def test_evidence_returns_without_calling_model(self):
        ods = MagicMock()
        ods.execute.return_value.mappings.return_value.all.return_value = []
        ods.execute.return_value.mappings.return_value.one.return_value = {'expired_stock': 0, 'expiring_stock': 0}
        ods.execute.return_value.scalar.return_value = None
        with patch('app.services.decision_summary.chat_completion', return_value='slow model') as model, \
             patch.object(api.settings, 'BI_QUERY_SOURCE', 'ods'):
            response = api.inventory_decisions(warehouse=['A'], refresh=True,
                current_user=SimpleNamespace(), ods_db=ods, db=MagicMock())
        model.assert_not_called()
        self.assertEqual(response['data']['metrics']['decision_count'], 0)

    def test_ads_path_skips_all_legacy_sales_queries(self):
        ods = MagicMock()
        ods.execute.return_value.mappings.return_value.all.return_value = []
        ods.execute.return_value.mappings.return_value.one.return_value = {'expired_stock': 0, 'expiring_stock': 0}
        with patch.object(api.settings, 'BI_QUERY_SOURCE', 'ads'), \
             patch.object(api, 'load_sales_evidence', return_value={'data_version': 'ready'}) as load:
            response = api.inventory_decisions(warehouse=['B', 'A', 'A'], refresh=True,
                current_user=None, ods_db=ods, db=None)['data']
        self.assertEqual(ods.execute.call_count, 2)
        self.assertEqual(response['warehouses_selected'], ['A', 'B'])
        self.assertEqual(response['sales']['data_version'], 'ready')
        self.assertIn('warehouse_0', ods.execute.call_args.args[1])
        load.assert_called_once()

    def test_slow_model_deduplicates_without_blocking_status(self):
        entered, release = Event(), Event()
        def slow(*args, **kwargs):
            entered.set()
            release.wait(3)
            return '建议'
        version = jobs.remember({'warehouses': ['A'], 'inventory': {'stock': 1}})
        with ThreadPoolExecutor(max_workers=1) as executor, \
             patch.object(jobs, '_executor', executor), \
             patch.object(jobs, 'SessionLocal', MagicMock()), \
             patch.object(jobs, 'chat_completion', side_effect=slow) as model:
            try:
                self.assertEqual(jobs.summary_state(version, ('A',), start=True)['ai_status'], 'pending')
                self.assertTrue(entered.wait(1))
                self.assertEqual(jobs.summary_state(version, ('A',))['ai_status'], 'pending')
                self.assertEqual(jobs.summary_state(version, ('A',), start=True, refresh=True)['ai_status'], 'pending')
                model.assert_called_once()
                with self.assertRaises(HTTPException): jobs.summary_state(version, ('B',))
            finally:
                release.set()
                executor.shutdown(wait=True)
        self.assertEqual(jobs.summary_state(version, ('A',))['ai_summary'], '建议')
        changed = jobs.remember({'warehouses': ['A'], 'inventory': {'stock': 2}})
        self.assertNotEqual(version, changed)
        self.assertEqual(jobs.summary_state(changed, ('A',))['ai_status'], 'idle')

    def test_failure_does_not_expose_provider_error(self):
        version = jobs.remember({'warehouses': ['Failure']})
        with ThreadPoolExecutor(max_workers=1) as executor, \
             patch.object(jobs, '_executor', executor), \
             patch.object(jobs, 'SessionLocal', MagicMock()), \
             patch.object(jobs, 'chat_completion', side_effect=RuntimeError('private-provider-key')):
            jobs.summary_state(version, ('Failure',), start=True)
            executor.shutdown(wait=True)
        state = jobs.summary_state(version, ('Failure',))
        self.assertEqual(state['ai_status'], 'unavailable')
        self.assertNotIn('private-provider-key', state['ai_summary'])

    def test_saturated_queue_returns_busy_and_expired_evidence_rejected(self):
        version = jobs.remember({'warehouses': ['Busy']})
        with patch.object(jobs, '_slots') as slots:
            slots.acquire.return_value = False
            self.assertEqual(jobs.summary_state(version, ('Busy',), start=True)['ai_status'], 'busy')
        with jobs._lock: jobs._evidence[version]['expires'] = 0
        with self.assertRaises(HTTPException): jobs.summary_state(version, ('Busy',))

    def test_summary_endpoints_preserve_permission_gate(self):
        app = FastAPI()
        app.include_router(api.router, dependencies=[Depends(require_permission('ai.decision.view'))])
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            role=SimpleNamespace(is_active=True, permissions=[]))
        with TestClient(app) as client:
            for method in (client.get, client.post):
                self.assertEqual(method('/ai/inventory-decisions/summary',
                    params={'evidence_id': 'a' * 64}).status_code, 403)

    def test_sales_ads_uses_ready_version_and_complete_previous_period(self):
        engine = create_engine('sqlite://')
        for table in (AdsPublishBatch, AdsSalesDaily, AdsSalesDailyChannel): table.__table__.create(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(AdsPublishBatch(data_version='v1', dataset='sales_daily', status='ready',
                source_start_date=date(2026, 1, 1), source_end_date=date(2026, 10, 20),
                created_at=datetime.now(), published_at=datetime.now()))
            for day, amount, quantity in [(date(2026, 10, 1), 100, 2), (date(2026, 9, 1), 50, 1)]:
                db.add(AdsSalesDaily(data_version='v1', sales_date=day, orders=1,
                    paid_amount=Decimal(amount), quantity=Decimal(quantity)))
                db.add(AdsSalesDailyChannel(data_version='v1', sales_date=day, channel='X',
                    orders=1, paid_amount=Decimal(amount), quantity=Decimal(quantity)))
            db.commit()
        with patch.object(decision_sales, 'AdsSessionLocal', factory):
            result = decision_sales.load_sales_evidence()
        self.assertEqual(result['current']['paid_amount'], 100)
        self.assertEqual(result['previous']['paid_amount'], 50)
        self.assertEqual(result['change']['paid_amount_rate'], 100)
        self.assertEqual(result['top_channels'][0]['paid_amount'], 100)


if __name__ == '__main__':
    unittest.main()
