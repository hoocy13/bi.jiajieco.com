import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routers import inventory_watches as api
from app.db.ads import get_ads_db
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.models.inventory_watch import InventoryWatch, InventoryWatchAudit
from app.services import inventory_watch as source


class SharedInventoryWatchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        InventoryWatch.__table__.create(self.engine)
        InventoryWatchAudit.__table__.create(self.engine)
        self.actor = SimpleNamespace(id=10, role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='sales.view')]))
        self.channels = [dict(code='A', name='天猫A', kind='线上', channel_id='1871821263807546624'), dict(code='B', name='天猫B', kind='线上', channel_id='1871821263807546625')]
        self.channel_reserved = [dict(product_code='SKU1', object_ids='1871821263807546624', remaining=4),
                                 dict(product_code='SKU1', object_ids='1871821263807546624, 1871821263807546625', remaining=6),
                                 dict(product_code='SKU1', object_ids='1871821263807546625', remaining=9)]
        self.stocks = {code: dict(product_code=code, product='同名商品', brand='品牌', product_type='正装', stock=100., available=60.) for code in ['SKU1', 'SKU2']}
        self.sold = [dict(channel='天猫A', product_code='SKU1', product='同名商品', brand='品牌', product_type='正装', quantity=10., amount=100.),
                     dict(channel='天猫B', product_code='SKU1', product='同名商品', brand='品牌', product_type='正装', quantity=-2., amount=-20.)]
        self.reserved = {'SKU1': dict(remaining=40., end_time=datetime.now() + timedelta(days=1), rules='手工释放、到期自动释放', order_count=2, expiring_count=1, overdue_count=0)}
        self.patches = [
            patch.object(source, 'channels', return_value=self.channels),
            patch.object(source, 'inventory', side_effect=lambda ads, warehouses=(), codes=None: ({k:v for k,v in self.stocks.items() if codes is None or k in codes}, {'inventory_version':'v1', 'inventory_updated_at':datetime(2026,11,3)})),
            patch.object(source, 'sales', side_effect=lambda ods,names,codes=None: ([r for r in self.sold if r['channel'] in names and (codes is None or r['product_code'] in codes)], {'sales_start':date(2026,10,1), 'sales_end':date(2026,10,31)})),
            patch.object(source, 'reservations', side_effect=lambda ods,codes,warehouses=(): ({k:v for k,v in self.reserved.items() if k in codes}, {})),
            patch.object(source, 'channel_reservations', side_effect=lambda ods,codes,warehouses=(): [r for r in self.channel_reserved if r['product_code'] in codes]),
        ]
        for p in self.patches: p.start()
        app = FastAPI()
        app.include_router(api.router, prefix='/api/v1')
        def admin_db():
            with Session(self.engine) as session:
                yield session
        app.dependency_overrides[get_db] = admin_db
        app.dependency_overrides[get_ods_db] = lambda: None
        app.dependency_overrides[get_ads_db] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: self.actor
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        for p in reversed(self.patches): p.stop()
        self.engine.dispose()

    def add(self, channels=('A','B'), codes=('SKU1',)):
        response = self.client.post('/api/v1/inventory-watches/batch', json=dict(channel_codes=list(channels), product_codes=list(codes)))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def get(self, **params):
        response = self.client.get('/api/v1/inventory-watches', params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def test_shared_across_users_idempotent_and_no_inventory_multiplication(self):
        self.assertEqual(self.add(), dict(added=2, existing=0))
        self.actor.id = 20
        self.assertEqual(self.add(), dict(added=0, existing=2))
        data = self.get()
        self.assertEqual(data['summary']['products'], 1)
        self.assertEqual(data['summary']['relations'], 2)
        self.assertEqual(data['rows'][0]['stock'], 100)
        self.assertEqual(data['rows'][0]['remaining'], 40)
        self.assertEqual(data['rows'][0]['quantity'], 8)
        with Session(self.engine) as db:
            self.assertEqual(len(db.scalars(select(InventoryWatchAudit)).all()), 2)

    def test_channel_view_and_combined_filters(self):
        self.add(codes=('SKU1','SKU2'))
        data = self.get(view='channel', channel_code='B', brand='品牌', product_type='正装', warehouse='上海仓库新', status='manual', keyword='SKU1')
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['rows'][0]['quantity'], -2)
        self.assertEqual(data['rows'][0]['stock'], 100)
        source.inventory.assert_called_with(None, ['上海仓库新'], ['SKU1','SKU2'])
        source.reservations.assert_called_with(None, ['SKU1','SKU2'], ['上海仓库新'])
        source.channel_reservations.assert_called_with(None, ['SKU1','SKU2'], ['上海仓库新'])

    def test_my_reservations_use_exact_ids_and_count_shared_records_once(self):
        self.add()
        self.assertEqual(self.get(channel_code='A')['rows'][0]['my_remaining'], 10)
        self.assertEqual(self.get(channel_code='B')['rows'][0]['my_remaining'], 15)
        self.assertEqual(self.get()['rows'][0]['my_remaining'], 19)
        self.channel_reserved.append(dict(product_code='SKU1', object_ids='11871821263807546624', remaining=100))
        self.assertEqual(self.get(channel_code='A')['rows'][0]['my_remaining'], 10)
        self.channels[0]['channel_id'] = None
        self.assertIsNone(self.get(channel_code='A')['rows'][0]['my_remaining'])

    def test_same_name_different_codes_zero_sales_and_missing_inventory(self):
        self.add(codes=('SKU1','SKU2'))
        del self.stocks['SKU2']
        rows = self.get(sort='product_code', direction='ascending')['rows']
        self.assertEqual([r['product_code'] for r in rows], ['SKU1','SKU2'])
        self.assertIsNone(rows[1]['stock'])
        self.assertEqual(rows[1]['quantity'], 0)

    def test_note_conflict_and_delete_only_one_channel(self):
        self.add()
        relation = self.get()['rows'][0]['relations'][0]
        endpoint = f"/api/v1/inventory-watches/{relation['id']}"
        body = dict(note='所有账号可见', revision=1)
        self.assertEqual(self.client.patch(endpoint, json=body).status_code, 200)
        self.assertEqual(self.client.patch(endpoint, json=body).status_code, 409)
        self.actor.id = 20
        self.assertEqual(self.get()['rows'][0]['relations'][0]['note'], '所有账号可见')
        self.assertEqual(self.client.delete(endpoint).status_code, 200)
        self.assertEqual(len(self.get()['rows'][0]['relations']), 1)
        with Session(self.engine) as db:
            self.assertEqual([r.action for r in db.scalars(select(InventoryWatchAudit).order_by(InventoryWatchAudit.id))], ['add','add','note','delete'])

    def test_candidates_signed_sales_and_existing_relations(self):
        self.add(channels=('A',))
        response = self.client.get('/api/v1/inventory-watches/candidates', params=[('channel_code','A'),('channel_code','B')])
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()['data']
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['rows'][0]['quantity'], 8)
        self.assertEqual(data['rows'][0]['watched_channels'], ['A'])
        self.assertEqual(len(data['rows'][0]['channel_sales']), 2)

    def test_candidate_categories_are_multi_select_and_rank_by_amount(self):
        self.stocks['SKU2']['product_type'] = '小样'
        self.stocks['SKU3'] = dict(product_code='SKU3', product='其他商品', brand='品牌', product_type='赠品', stock=10, available=10)
        self.sold.append(dict(channel='天猫A', product_code='SKU2', product='小样商品', brand='品牌', product_type='小样', quantity=2, amount=300))
        default = self.client.get('/api/v1/inventory-watches/candidates', params={'mode':'all'})
        self.assertEqual(default.status_code, 200, default.text)
        self.assertEqual(default.json()['data']['pagination']['total'], 3)
        response = self.client.get('/api/v1/inventory-watches/candidates', params=[
            ('channel_code','A'), ('brand','品牌'), ('product_type','正装'), ('product_type','小样'),
            ('sort','amount'), ('direction','descending'), ('mode','sales')])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([r['product_code'] for r in response.json()['data']['rows']], ['SKU2','SKU1'])
        # A single repeated-query value remains compatible with existing callers.
        single = self.client.get('/api/v1/inventory-watches/candidates', params={'mode':'all','product_type':'小样'})
        self.assertEqual(single.json()['data']['pagination']['total'], 1)

    def test_invalid_batch_is_atomic_and_permission_enforced(self):
        response = self.client.post('/api/v1/inventory-watches/batch', json=dict(channel_codes=['A','UNKNOWN'], product_codes=['SKU1']))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.get()['pagination']['total'], 0)
        self.actor.role.permissions = []
        self.assertEqual(self.client.get('/api/v1/inventory-watches').status_code, 403)
        self.assertEqual(self.client.post('/api/v1/inventory-watches/batch', json=dict(channel_codes=['A'], product_codes=['SKU1'])).status_code, 403)

    def test_sold_out_reference_sku_can_be_added_to_different_channel(self):
        del self.stocks['SKU1']
        self.sold = [self.sold[0]]  # Only channel A has sales; target B does not.
        self.assertEqual(self.add(channels=('B',)), dict(added=1, existing=0))

    def test_month_boundary_and_stable_pagination(self):
        self.assertEqual(source.recent_30_days(date(2026,1,1)), (date(2025,12,2), date(2025,12,31)))
        self.assertEqual(source.recent_30_days(date(2024,3,1)), (date(2024,1,31), date(2024,2,29)))
        rows = [dict(product_code=f'{i:02}', quantity=1) for i in reversed(range(25))]
        page, pagination = source.page_rows(rows, 2, 10, 'quantity', True)
        self.assertEqual([r['product_code'] for r in page], [f'{i:02}' for i in range(10,20)])
        self.assertEqual(pagination['total'], 25)

    def test_expiring_filter_does_not_hide_sku_with_an_older_overdue_reservation(self):
        self.add()
        self.reserved['SKU1'].update(end_time=datetime.now() - timedelta(days=30), overdue_count=1)
        self.assertEqual(self.get(status='expiring')['pagination']['total'], 1)
        self.assertEqual(self.get(status='overdue')['pagination']['total'], 1)
        self.assertEqual(self.get()['summary']['expiring_products'], 1)

    def test_failed_batch_rolls_back_all_relations_and_audits(self):
        def fail_audit(*args):
            raise RuntimeError('simulate audit storage failure')
        event.listen(InventoryWatchAudit, 'before_insert', fail_audit)
        try:
            with self.assertRaises(RuntimeError):
                self.add(codes=('SKU1','SKU2'))
        finally:
            event.remove(InventoryWatchAudit, 'before_insert', fail_audit)
        self.assertEqual(self.get()['pagination']['total'], 0)
        with Session(self.engine) as db:
            self.assertEqual(db.scalars(select(InventoryWatchAudit)).all(), [])

    def test_deleted_ids_are_not_reused_by_new_shared_relations(self):
        self.add(channels=('A',))
        old_id = self.get()['rows'][0]['relations'][0]['id']
        self.client.delete(f'/api/v1/inventory-watches/{old_id}')
        self.add(channels=('B',))
        new_id = self.get()['rows'][0]['relations'][0]['id']
        self.assertGreater(new_id, old_id)
        self.client.delete(f'/api/v1/inventory-watches/{old_id}')
        self.assertEqual(self.get()['pagination']['total'], 1)

    def test_channel_picker_only_lists_configured_channels_and_refreshes_after_delete(self):
        self.add(channels=('A',))
        with patch.object(source, 'rows', return_value=[]):
            response = self.client.get('/api/v1/inventory-watches/options')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['data']['configured_channels'], [dict(code='A', name='天猫A', product_count=1)])
            relation = self.get()['rows'][0]['relations'][0]
            self.client.delete(f"/api/v1/inventory-watches/{relation['id']}")
            self.assertEqual(self.client.get('/api/v1/inventory-watches/options').json()['data']['configured_channels'], [])

    def test_details_query_only_positive_stock_and_current_remaining_reservations(self):
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE ads_inventory_health_item (data_version TEXT, product_code TEXT, warehouse TEXT, stock REAL, available_stock REAL)'))
            c.execute(text("INSERT INTO ads_inventory_health_item VALUES ('v1','SKU1','有库存',100,50),('v1','SKU1','零库存',0,0),('v1','SKU1','负库存',-2,-2),('v1','SKU1','高可用',80,70)"))
            c.execute(text('CREATE TABLE `预留单查询` (`预留单ID` TEXT, `预留单号` TEXT, `状态` TEXT, `预留对象` TEXT, `预留仓库` TEXT, `申请时间` TEXT, `使用起始日期` TEXT, `使用结束日期` TEXT, `到期释放` TEXT)'))
            c.execute(text("INSERT INTO `预留单查询` VALUES ('1','R1','执行中','渠道A','有库存','2026-10-01 12:34:56','2026-10-02 01:02:03','2026-11-06 23:59:59','手工释放'),('2','R2','已释放','渠道A','有库存',NULL,NULL,NULL,NULL)"))
            c.execute(text('CREATE TABLE `预留单货品明细` (`明细ID` TEXT, `预留单ID` TEXT, `货品编号` TEXT, `预留数量` REAL, `剩余数量` REAL, `已用数量` REAL, `已释放数量` REAL)'))
            c.execute(text("INSERT INTO `预留单货品明细` VALUES ('1','1','SKU1',10,6,4,0),('2','1','SKU1',10,0,10,0),('3','2','SKU1',10,2,8,0),('4','1','SKU2',20,20,0,0)"))
        def read_db():
            with Session(self.engine) as db:
                yield db
        self.client.app.dependency_overrides[get_ods_db] = read_db
        self.client.app.dependency_overrides[get_ads_db] = read_db
        response = self.client.get('/api/v1/inventory-watches/products/SKU1')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()['data']
        self.assertEqual(data['stocks'], [dict(warehouse='高可用', stock=80, available=70),dict(warehouse='有库存', stock=100, available=50)])
        self.assertEqual(data['pagination']['total'], 1)
        self.assertEqual(data['reservations'][0]['remaining'], 6)
        self.assertEqual(data['reservations'][0]['number'], 'R1')
        self.assertEqual(data['reservations'][0]['end_time'], '2026-11-06 23:59:59')
        response = self.client.get('/api/v1/inventory-watches/products/SKU1', params={'warehouse':'零库存'})
        self.assertEqual(response.json()['data']['stocks'], [])
        self.assertEqual(response.json()['data']['pagination']['total'], 0)
        with self.engine.begin() as c:
            c.execute(text('ALTER TABLE `预留单查询` ADD COLUMN `对象类型` TEXT'))
            c.execute(text('ALTER TABLE `预留单查询` ADD COLUMN `预留对象ID` TEXT'))
            c.execute(text("UPDATE `预留单查询` SET `对象类型`='渠道', `预留对象ID`='1871821263807546624' WHERE `预留单ID`='1'"))
        raw = self.engine.raw_connection()
        raw.create_function('FIND_IN_SET', 2, lambda key,csv: int(str(key) in csv.split(',')))
        raw.close()
        mine = self.client.get('/api/v1/inventory-watches/products/SKU1', params={'channel_code':'A','mine_only':'true'})
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual(mine.json()['data']['pagination']['total'], 1)
        other = self.client.get('/api/v1/inventory-watches/products/SKU1', params={'channel_code':'B','mine_only':'true'})
        self.assertEqual(other.json()['data']['pagination']['total'], 0)
        missing = self.client.get('/api/v1/inventory-watches/products/SKU1', params={'channel_code':'missing','mine_only':'true'})
        self.assertEqual(missing.status_code, 422)


class SalesCacheIsolationTests(unittest.TestCase):
    def test_channels_codes_and_month_are_part_of_aggregate_cache(self):
        db = SimpleNamespace(get_bind=lambda: self)
        with patch.object(source, 'rows', return_value=[] ) as query:
            source.sales(db, ['A', 'B'], ['SKU1'])
            source.sales(db, ['B', 'A'], ['SKU1'])
            self.assertEqual(query.call_count, 1)
            source.sales(db, ['A'], ['SKU1'])
            source.sales(db, ['A'], ['SKU2'])
            source.sales(db, ['A'], None)
            source.sales(db, ['A'], [])
            self.assertEqual(query.call_count, 5)
            with patch.object(source, 'recent_30_days', return_value=(date(2026,9,1),date(2026,9,30))):
                source.sales(db, ['A'], ['SKU1'])
            self.assertEqual(query.call_count, 6)


if __name__ == '__main__':
    unittest.main()
