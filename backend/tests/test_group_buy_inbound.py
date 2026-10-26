import unittest
import json
from copy import deepcopy
from datetime import date, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import xlsxwriter
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user
from app.api.routers import group_buy, group_buy_inbound
from app.db.session import get_db
from app.models.group_buy import GroupBuyBatch, GroupBuyChange
from app.models.group_buy_inbound import InboundAlias, InboundAudit, InboundBinding, InboundCounter, InboundLine, InboundSupplier, InboundSync, InboundSubstitution, InboundReceiptHold, InboundOrderCollection
from app.schemas.group_buy_inbound import InboundScope
from app.services import group_buy_inbound as service


class InboundTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        for model in (GroupBuyBatch, GroupBuyChange, InboundCounter, InboundAlias, InboundBinding, InboundLine, InboundAudit, InboundSupplier, InboundSync, InboundSubstitution, InboundReceiptHold, InboundOrderCollection):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.document = {'sources': [{'id': 's', 'name': '上海市百一店', 'counter': True}],
            'columns': [{'id': 'c', 'source_id': 's', 'customer': '客户甲'}],
            'products': [{'id': 'p', 'code': 'ORDER-A', 'barcode': '001234', 'name': '商品甲', 'price': '12.35',
                'abc': '', 'pcb': 20, 'orders': {'s': 10}, 'allocations': {'c': 3}, 'quotas': {'s': 10}}]}
        self.batch = GroupBuyBatch(month='2026-10', brand='兰蔻', name='第一批', document=deepcopy(self.document), created_by='tester')
        self.db.add(self.batch); self.db.commit()
        self.scope = InboundScope(start_date=date(2026,10,1), end_date=date(2026,10,31), brand='兰蔻')
        self.user = SimpleNamespace(username='tester', role=SimpleNamespace(is_active=True, permissions=[SimpleNamespace(code='group_buy.manage')]))
        app = FastAPI(); app.include_router(group_buy_inbound.router, prefix='/api/v1'); app.include_router(group_buy.router, prefix='/api/v1')
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.base = '/api/v1/group-buy/inbound'
        self.params = {'start_date': '2026-10-01', 'end_date': '2026-10-31', 'brand': '兰蔻', 'batch_id': self.batch.id}

    def tearDown(self):
        self.client.close(); self.db.close(); self.engine.dispose()

    def row(self, rec='r1', barcode='001234', quantity=6, **extra):
        return {'doc_id': 'doc1', 'rec_id': rec, 'receipt_number': 'CRK1', 'receipt_time': datetime(2026,10,22,14,28),
            'supplier': '兰蔻 上海一百  百联', 'warehouse': '上海仓库新', 'remark': '10月', 'related_number': 'RK1',
            'reversal_status': '1', 'code': 'OTHER-CODE', 'name': '其他名称', 'barcode': barcode, 'brand': '兰蔻',
            'unit': '支', 'quantity': quantity, 'lot': rec, 'source_updated_at': datetime(2026,10,23,8), **extra}

    def sync(self, rows):
        with patch.object(service, 'load_source', return_value=rows):
            return service.sync_source(self.db, None, self.scope, 'tester')

    def listing(self, **extra):
        response = self.client.get(self.base+'/lines', params={k:v for k,v in {**self.params, **extra}.items() if v is not None})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['data']

    def mapping(self):
        response = self.client.post(self.base+'/mapping', json={'batch_id': self.batch.id, 'revision': 1, 'source_id': 's', 'supplier': '兰蔻 上海一百 百联'})
        self.assertEqual(response.status_code, 200, response.text)

    def action(self, rows, action='confirm', **extra):
        return self.client.post(self.base+'/actions', json={'action': action, 'lines': [{'id': r['id'], 'revision': r['revision']} for r in rows],
            'batch_id': self.batch.id, 'batch_revision': 1, 'note': '' if action=='confirm' else '核对处理', **extra})

    def test_barcode_only_confirmation_idempotency_and_no_order_or_allocation_change(self):
        self.sync([self.row(), self.row('r2',quantity=4)])
        self.assertEqual(self.listing()['rows'][0]['reason'], '往来单位未对应柜台')
        self.mapping()
        rows = self.listing(state='ready')['rows']
        self.assertEqual(len(rows),2)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'], {})
        self.assertEqual(self.action(rows).status_code,200)
        response = self.client.get(self.base+f'/progress/{self.batch.id}',params={'product_id':'p','source_id':'s'}).json()['data']
        self.assertEqual(response['received'],{'p:s':10}); self.assertEqual(len(response['details']),2)
        self.assertEqual(self.action(rows).status_code,409)
        self.sync([self.row(),self.row('r2',quantity=4)])
        self.assertEqual(self.db.query(InboundLine).count(),2)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{'p:s':10})
        self.db.refresh(self.batch)
        self.assertEqual(self.batch.document,self.document); self.assertEqual(self.batch.revision,1)

    def assignments(self, rows, **extra):
        return [{'id': r['id'], 'revision': r['revision'], 'batch_id': self.batch.id,
                 'batch_revision': self.batch.revision, 'source_id': 's', **extra} for r in rows]

    def receipts(self, **extra):
        r = self.client.get(self.base+'/receipts', params={**self.params, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()['data']

    def test_receipt_grouping_filters_keep_whole_document_and_warehouse_scope(self):
        self.sync([self.row(), self.row('r2', barcode='other'), self.row('r3', warehouse='其他仓库', doc_id='doc2')])
        listed = self.receipts(keyword='001234')
        self.assertEqual(listed['total'], 1)
        self.assertEqual(listed['rows'][0]['item_count'], 2)
        detail = self.client.get(self.base+'/receipts/doc1', params={'brand':'兰蔻'}).json()['data']
        self.assertEqual(len(detail['rows']), 2)
        self.assertEqual(self.client.get(self.base+'/receipts/doc2', params={'brand':'兰蔻'}).status_code, 404)
        outside = self.db.scalar(select(InboundLine).where(InboundLine.doc_id=='doc2'))
        r = self.client.post(self.base+'/receipt-confirmations', json={'lines':self.assignments([{'id':outside.id,'revision':outside.revision}])})
        self.assertEqual(r.status_code, 409)

    def test_one_receipt_split_across_months_atomic_and_partial_status(self):
        self.sync([self.row(),self.row('r2')])
        other = GroupBuyBatch(month='2026-09',brand='兰蔻',name='九月批次',document=deepcopy(self.document),created_by='tester')
        self.db.add(other);self.db.commit()
        rows = self.receipts()['rows'][0]['lines']
        first = self.assignments(rows[:1])
        response = self.client.post(self.base+'/receipt-confirmations',json={'lines':first})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.receipts()['rows'][0]['status'],'partial')
        remaining = self.assignments(rows[1:]);remaining[0].update(batch_id=other.id,batch_revision=other.revision)
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':remaining}).status_code,200)
        done = self.receipts(state='done')['rows'][0]
        self.assertEqual(done['processed_count'],2);self.assertEqual(len(done['destinations']),2)
        self.assertEqual(self.client.get(self.base+f'/progress/{other.id}').json()['data']['received'],{'p:s':6})
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':first}).status_code,409)
        self.db.refresh(self.batch);self.assertEqual(self.batch.document,self.document)

    def test_substitution_99_plus_1_preserves_actual_sku_and_release(self):
        doc=deepcopy(self.batch.document);doc['products'][0]['orders']['s']=100
        self.batch.document=doc;self.db.commit()
        self.sync([self.row(quantity=99),self.row('r2',barcode='SUBSTITUTE',quantity=1,name='替代商品乙')])
        rows=self.receipts()['rows'][0]['lines'];payload=self.assignments(rows)
        payload[1].update(mode='substitute',product_id='p',credit_quantity=1,note='柜台缺货补商品乙')
        r=self.client.post(self.base+'/receipt-confirmations',json={'lines':payload})
        self.assertEqual(r.status_code,200,r.text)
        result=self.client.get(self.base+f'/progress/{self.batch.id}',params={'product_id':'p'}).json()['data']
        self.assertEqual(result['received'],{'p:s':100});self.assertEqual(result['normal_received'],{'p:s':99})
        self.assertEqual(result['substituted'],{'p:s':1})
        substitute=next(r for r in result['details'] if r['mode']=='substitute')
        self.assertEqual(substitute['barcode'],'SUBSTITUTE');self.assertEqual(substitute['name'],'替代商品乙')
        self.assertEqual(substitute['credit_quantity'],1)
        self.assertEqual(self.action([substitute],action='release').status_code,200)
        self.assertIsNone(self.db.get(InboundSubstitution,substitute['id']))
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{'p:s':99})
        self.db.refresh(self.batch);self.assertEqual(self.batch.document,doc)

    def test_substitution_validation_and_multi_batch_conflict_roll_back_all(self):
        self.sync([self.row(),self.row('r2',barcode='sub')])
        rows=self.receipts()['rows'][0]['lines'];payload=self.assignments(rows)
        payload[1].update(mode='substitute',product_id='p',credit_quantity=1,note='')
        r=self.client.post(self.base+'/receipt-confirmations',json={'lines':payload})
        self.assertEqual(r.status_code,422)
        self.assertEqual(self.db.query(InboundLine).filter_by(status='confirmed').count(),0)
        payload[1].update(note='替代',batch_revision=99)
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':payload}).status_code,409)
        self.assertEqual(self.db.query(InboundLine).filter_by(status='confirmed').count(),0)
        self.assertEqual(self.db.query(InboundSubstitution).count(),0)

    def test_substitution_source_correction_requires_review(self):
        self.sync([self.row(barcode='sub',quantity=2)])
        payload=self.assignments(self.receipts()['rows'][0]['lines'],mode='substitute',product_id='p',credit_quantity=1,note='两件抵一件')
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':payload}).status_code,200)
        self.sync([self.row(barcode='sub',quantity=3)])
        result=self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']
        self.assertEqual(result['received'],{});self.assertEqual(result['review_count'],1)

    def test_receipt_routes_enforce_permissions(self):
        self.user.role.permissions=[]
        for path in ('/receipts','/receipts/doc1'):
            self.assertEqual(self.client.get(self.base+path,params=self.params).status_code,403)
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':self.assignments([{'id':1,'revision':1}])}).status_code,403)

    def receipt_detail(self, doc='doc1'):
        response=self.client.get(self.base+'/receipts/'+doc,params={'brand':'兰蔻'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['data']

    def test_auto_match_unique_mapping_is_read_only_and_skips_processed(self):
        self.sync([self.row()])
        self.assertEqual(self.receipt_detail()['auto_count'],0)
        self.mapping()
        result=self.receipt_detail()
        self.assertEqual(result['auto_count'],1)
        self.assertEqual(result['rows'][0]['recommendation']['batch_id'],self.batch.id)
        self.assertEqual(result['rows'][0]['recommendation']['waiting'],10)
        self.assertEqual(self.db.query(InboundLine).filter_by(status='confirmed').count(),0)
        self.action(self.listing()['rows'])
        self.assertEqual(self.receipt_detail()['auto_count'],0)

    def test_auto_match_cross_month_each_line_gets_own_target(self):
        other=GroupBuyBatch(month='2026-09',brand='兰蔻',name='九月',document=deepcopy(self.document),created_by='tester')
        doc=deepcopy(self.document);doc['products'][0]['barcode']='002'
        self.batch.document=doc;self.db.add(other);self.db.commit();self.mapping()
        self.sync([self.row(),self.row('r2',barcode='002',quantity=4)])
        result=self.receipt_detail()
        self.assertEqual(result['auto_count'],2)
        self.assertEqual([r['recommendation']['batch_id'] for r in result['rows']],[other.id,self.batch.id])

    def test_auto_match_competing_batches_uses_remaining_only_when_unique(self):
        self.mapping();self.sync([self.row()]);self.action(self.listing()['rows'])
        other=GroupBuyBatch(month='2026-09',brand='兰蔻',name='九月',document=deepcopy(self.document),created_by='tester')
        self.db.add(other);self.db.commit()
        self.sync([self.row(),self.row('r2',doc_id='doc2',quantity=6)])
        result=self.receipt_detail('doc2')
        self.assertEqual(result['auto_count'],1)
        self.assertEqual(result['rows'][0]['recommendation']['batch_id'],other.id)
        self.sync([self.row(),self.row('r2',doc_id='doc2',quantity=3)])
        result=self.receipt_detail('doc2')
        self.assertEqual(result['auto_count'],0)
        self.assertIn('多个批次',result['rows'][0]['auto_match_reason'])

    def test_auto_match_shared_capacity_and_duplicate_barcodes_need_review(self):
        self.mapping();self.sync([self.row(),self.row('r2')])
        result=self.receipt_detail()
        self.assertEqual(result['auto_count'],0)
        self.assertTrue(all('合计超过' in r['auto_match_reason'] for r in result['rows']))
        doc=deepcopy(self.document);doc['products'].append({**doc['products'][0],'id':'duplicate'})
        self.batch.document=doc;self.db.commit()
        result=self.receipt_detail()
        self.assertEqual(result['auto_count'],0)
        self.assertTrue(all('重复' in r['auto_match_reason'] for r in result['rows']))

    def hold(self, waiting=True, revision=0, **extra):
        return self.client.post(self.base+'/receipts/doc1/hold',params={'brand':'兰蔻'},json={
            'waiting':waiting,'revision':revision,'month':'2026-10','counter':'上海市百一店','note':'柜台没给下单表',**extra})

    def test_missing_order_hold_preserves_receipts_orders_and_blocks_both_confirm_routes(self):
        self.sync([self.row(),self.row('r2',quantity=2)]);self.mapping()
        first=self.listing()['rows'][0]
        self.assertEqual(self.action([first]).status_code,200)
        progress_before=self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received']
        versions=[(l.id,l.revision,l.status,l.snapshot) for l in self.db.scalars(select(InboundLine))]
        response=self.hold();self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.receipts()['total'],0)
        waiting=self.receipts(state='waiting')['rows'][0]
        self.assertEqual(waiting['item_count'],2);self.assertEqual(waiting['pending_count'],1)
        detail=self.receipt_detail();self.assertEqual(detail['auto_count'],0);self.assertTrue(detail['hold']['waiting'])
        pending=[r for r in detail['rows'] if r['status']=='ready']
        self.assertEqual(self.action(pending).status_code,409)
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':self.assignments(pending)}).status_code,409)
        self.assertEqual([(l.id,l.revision,l.status,l.snapshot) for l in self.db.scalars(select(InboundLine))],versions)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],progress_before)
        self.db.refresh(self.batch);self.assertEqual(self.batch.document,self.document)

    def test_missing_order_resume_recommends_again_and_stale_hold_is_rejected(self):
        self.sync([self.row()]);self.mapping()
        self.assertEqual(self.hold().status_code,200)
        self.assertEqual(self.hold(revision=0).status_code,409)
        self.assertEqual(self.hold(waiting=False,revision=1).status_code,200)
        detail=self.receipt_detail();self.assertFalse(detail['hold']['waiting']);self.assertEqual(detail['auto_count'],1)
        self.assertEqual(self.client.post(self.base+'/receipt-confirmations',json={'lines':self.assignments(detail['rows'])}).status_code,200)
        self.assertEqual(self.hold(revision=2).status_code,422)

    def test_collection_checklist_is_independent_and_preserves_received_state(self):
        self.sync([self.row()]);self.assertEqual(self.hold().status_code,200)
        params={'month':'2026-10','brand':'兰蔻'}
        records=self.client.get(self.base+'/order-collections',params=params).json()['data']
        self.assertEqual(len(records),1);self.assertEqual(records[0]['status'],'missing');self.assertIsNone(records[0]['batch_id'])
        body={**params,'revision':1,'counter':'上海市百一店','status':'received','note':'已收到，尚未导入'}
        response=self.client.post(self.base+'/order-collections',json=body)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.post(self.base+'/order-collections',json=body).status_code,409)
        self.assertEqual(self.hold(revision=1).status_code,200)
        records=self.client.get(self.base+'/order-collections',params=params).json()['data']
        self.assertEqual(records[0]['status'],'received')
        self.assertTrue(self.receipt_detail()['hold']['waiting'])
        self.assertEqual(self.db.query(InboundLine).filter_by(status='confirmed').count(),0)

    def test_missing_orders_permissions_and_scope(self):
        self.sync([self.row()])
        self.assertEqual(self.client.post(self.base+'/receipts/unknown/hold',params={'brand':'兰蔻'},json={
            'revision':0,'waiting':True,'month':'2026-10','counter':'柜台'}).status_code,404)
        self.user.role.permissions=[]
        self.assertEqual(self.hold().status_code,403)
        self.assertEqual(self.client.get(self.base+'/order-collections',params={'month':'2026-10','brand':'兰蔻'}).status_code,403)

    def test_arrival_totals_do_not_offset_other_counters_and_sort_all_products(self):
        doc=deepcopy(self.document)
        doc['sources'] += [{'id':'t','name':'另一柜台','counter':True},{'id':'stock','name':'现货','counter':False}]
        doc['products'][0]['orders']={'s':10,'t':10,'stock':99}
        doc['products'].append({**deepcopy(doc['products'][0]),'id':'q','code':'ORDER-B','barcode':'002','orders':{'t':7}})
        self.batch.document=doc;self.db.commit()
        self.sync([self.row(quantity=15),self.row('r2',quantity=5)])
        payload=self.assignments(self.receipts()['rows'][0]['lines']);payload[1]['source_id']='t'
        response=self.client.post(self.base+'/receipt-confirmations',json={'lines':payload})
        self.assertEqual(response.status_code,200,response.text)
        result=self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']
        self.assertEqual(result['products']['p'],{'ordered':20,'received_total':20,'waiting_total':5,'over_received':5})
        self.assertEqual(result['summary'],{'ordered':27,'received_total':20,'waiting_total':12,'over_received':5})
        response=self.client.get(f'/api/v1/group-buy/batches/{self.batch.id}',params={'sort_by':'waiting_total','sort_order':'desc','all_rows':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([p['id'] for p in response.json()['data']['rows']],['q','p'])
        response=self.client.get(f'/api/v1/group-buy/batches/{self.batch.id}',params={'sort_by':'received_total','sort_order':'desc','keyword':'ORDER-A','all_rows':True})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(response.json()['data']['rows']),1)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}',params={'product_id':'p','source_id':'s'}).json()['data']['summary'],result['summary'])

    def test_blank_unmatched_and_ambiguous_barcodes_do_not_fall_back_to_code(self):
        self.sync([self.row(barcode=''),self.row('r2',barcode='OTHER',code='ORDER-A')]); self.mapping()
        rows = self.listing()['rows']
        self.assertTrue(all(r['status']=='pending' for r in rows))
        self.assertTrue(any(r['reason']=='入库缺少条码' for r in rows))
        self.assertEqual(self.action(rows).status_code,409)
        self.sync([self.row()])
        doc=deepcopy(self.batch.document); doc['products'].append({**doc['products'][0],'id':'p2','code':'ORDER-B'})
        self.batch.document=doc; self.db.commit()
        self.assertTrue(any(r['reason']=='同条码对应多个下单商品' for r in self.listing()['rows']))

    def test_source_quantity_updates_recompute_and_identity_changes_suspend_link(self):
        self.sync([self.row()]); self.mapping(); self.action(self.listing()['rows'])
        self.sync([self.row(quantity=12)])
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{'p:s':12})
        self.sync([self.row(barcode='999',quantity=12)])
        p=self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']
        self.assertEqual(p['received'],{}); self.assertEqual(p['review_count'],1)
        row=self.listing()['rows'][0]
        self.assertIn('解除',row['reason']);self.assertEqual(self.action([row]).status_code,409)
        self.assertEqual(self.action([row],action='release').status_code,200)

    def test_signed_quantity_kept_unknown_reversal_requires_review_but_units_do_not(self):
        self.sync([self.row(quantity=-2),self.row('r2',reversal_status='9'),self.row('r3',unit='箱')]);self.mapping()
        rows=self.listing()['rows']
        ready=[r for r in rows if r['status']=='ready']
        self.assertEqual(len(ready),2);self.assertTrue(any(r['quantity']=='-2' for r in ready))
        self.assertEqual(self.action(ready).status_code,200)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{'p:s':4})
        self.assertTrue(any('红蓝冲' in r['reason'] for r in rows));self.assertFalse(any('单位' in r['reason'] for r in rows))

    def test_units_are_reference_only_and_unit_edits_do_not_suspend_arrivals(self):
        units = ['默认', '箱', '', '未知单位']
        rows = [self.row(str(i), quantity=i+2, unit=unit) for i, unit in enumerate(units)]
        self.sync(rows); self.mapping()
        ready = self.listing(state='ready')['rows']
        self.assertEqual(len(ready), 4)
        self.assertEqual(self.action(ready).status_code, 200)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'], {'p:s': 14})
        for row in rows:
            row['unit'] = '改后的单位'
        self.sync(rows)
        progress = self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']
        self.assertEqual(progress['received'], {'p:s': 14})
        self.assertEqual(progress['review_count'], 0)
        self.assertEqual(self.listing(state='confirmed')['total'], 4)
        self.assertEqual(self.batch.document['products'][0]['pcb'], 20)

    def test_comparison_previews_orders_and_receipts_without_changing_mapping(self):
        self.sync([self.row(unit='默认')])
        line = self.listing()['rows'][0]
        doc = deepcopy(self.batch.document)
        doc['sources'].append({'id': 'other', 'name': '其他柜台', 'counter': True})
        doc['products'][0]['orders']['other'] = 4
        doc['products'].append({**deepcopy(doc['products'][0]), 'id': 'p2', 'code': 'SECOND', 'barcode': '999', 'name': '商品乙'})
        self.batch.document = doc; self.db.commit()
        def comparison(**params):
            result = self.client.get(self.base+f"/comparison/{line['id']}", params={'batch_id': self.batch.id, **params})
            self.assertEqual(result.status_code, 200, result.text)
            return result.json()['data']
        unbound = comparison(source_id='s')
        self.assertFalse(unbound['mapping_matches'])
        self.assertEqual(unbound['matching_count'], 1)
        self.assertEqual(unbound['orders'][0]['barcode'], '001234')
        self.assertEqual(unbound['orders'][0]['ordered'], 10)
        self.assertEqual(unbound['orders'][0]['received'], 0)
        self.assertEqual(self.db.query(InboundAlias).count(), 0)
        self.mapping()
        mapped = comparison()
        self.assertEqual(mapped['source_id'], 's')
        self.assertTrue(mapped['mapping_matches'])
        self.assertEqual(mapped['receipt']['status'], 'ready')
        self.assertEqual(mapped['receipt']['unit'], '默认')
        self.assertFalse(comparison(source_id='other')['mapping_matches'])
        self.assertEqual(self.action(self.listing(state='ready')['rows']).status_code, 200)
        linked = comparison()
        self.assertEqual(linked['orders'][0]['received'], 6)
        self.assertEqual(linked['orders'][0]['waiting'], 4)
        self.assertEqual(linked['receipt']['status'], 'confirmed')
        self.assertEqual(self.client.get(self.base+f"/comparison/{line['id']}", params={'batch_id':self.batch.id,'source_id':'bad'}).status_code, 422)
        self.assertEqual(self.client.get(self.base+'/comparison/9999').status_code, 404)

    def test_actions_atomic_multi_candidate_batch_and_filters_pagination(self):
        self.sync([self.row(str(i),barcode='001234' if i%2==0 else 'bad',quantity=i) for i in range(24)]);self.mapping()
        page=self.listing(page_size=10)
        self.assertEqual(page['total'],24);self.assertEqual(len(page['rows']),10);self.assertEqual(page['receipt_count'],1)
        filtered=self.listing(state='ready',keyword='OTHER-CODE',supplier='兰蔻 上海一百 百联',sort_by='quantity',sort_order='asc')
        self.assertEqual(filtered['total'],12);self.assertEqual(filtered['rows'][0]['quantity'],'0')
        selected=sorted(self.listing()['rows'][:2], key=lambda r:r['status']!='ready')
        self.assertEqual(self.action(selected).status_code,409)
        self.assertEqual(self.db.query(InboundLine).filter(InboundLine.status=='confirmed').count(),0)
        other=GroupBuyBatch(month='2026-11',brand='兰蔻',name='下一批',document=deepcopy(self.document),created_by='tester')
        self.db.add(other);self.db.commit()
        result=self.listing(state='ready',batch_id=None)
        self.assertEqual(result['total'],0)
        self.assertTrue(any('多个' in r['reason'] for r in self.listing(batch_id=None)['rows']))

    def test_supplier_and_product_column_filters_combine_before_pagination(self):
        self.sync([self.row(str(i), supplier='供应商一' if i % 2 == 0 else '供应商二',
                           code='CODE-A' if i < 12 else 'CODE-B', barcode='001234' if i % 3 == 0 else 'bad')
                   for i in range(24)])
        first = self.listing(page_size=10)
        self.assertEqual(first['total'], 24)
        self.assertEqual(len(first['rows']), 10)
        self.assertEqual({o['value'] for o in first['supplier_filters']}, {'供应商一', '供应商二'})
        self.assertEqual(len(first['product_filters']), 4)
        keys = {tuple(json.loads(o['value'])): o['value'] for o in first['product_filters']}
        filtered = self.listing(supplier_names=['供应商一'], product_keys=[keys[('CODE-A', '001234')]], keyword='OTHER')
        self.assertEqual(filtered['total'], 0)
        filtered = self.listing(supplier_names=['供应商一'], product_keys=[keys[('CODE-A', '001234')]])
        self.assertEqual(filtered['total'], 2)
        self.assertTrue(all(r['supplier'] == '供应商一' and r['code'] == 'CODE-A' and r['barcode'] == '001234' for r in filtered['rows']))
        self.assertEqual(len(filtered['product_filters']), 4)
        multiple = self.listing(supplier_names=['供应商一', '供应商二'],
                                product_keys=[keys[('CODE-A', '001234')], keys[('CODE-B', '001234')]])
        self.assertEqual(multiple['total'], 8)
        self.assertEqual(self.listing(supplier_names=['供应商一'], state='confirmed')['total'], 0)
        response = self.client.get(self.base+'/lines', params={**self.params, 'product_keys': ['x']*101})
        self.assertEqual(response.status_code, 422)

    def test_state_filters_keep_counts_and_use_all_matching_rows(self):
        self.sync([self.row(str(i), barcode='001234' if i % 2 == 0 else 'bad', quantity=i)
                   for i in range(24)])
        self.mapping()
        ready = self.listing(state='ready')['rows']
        self.assertEqual(self.action(ready[:1]).status_code, 200)
        self.assertEqual(self.action(ready[1:2], action='exclude').status_code, 200)
        expected = {'pending': 22, 'ready': 10, 'confirmed': 1, 'excluded': 1}
        for state, total in expected.items():
            result = self.listing(state=state, page_size=10)
            self.assertEqual(result['total'], total)
            self.assertEqual(result['summary'], {'pending': 12, 'ready': 10, 'confirmed': 1, 'excluded': 1})
            self.assertTrue(all(r['status'] in ('pending', 'ready') if state == 'pending'
                                else r['status'] == state for r in result['rows']))
            self.assertEqual(len(result['rows']), min(10, total))
        combined = self.listing(state='confirmed', supplier='兰蔻 上海一百 百联', keyword='OTHER-CODE')
        self.assertEqual(combined['total'], 1)
        self.assertEqual(self.listing(state='excluded', keyword='NOT-FOUND')['total'], 0)

    def test_bulk_exclude_restore_shared_reason_and_atomic_conflict(self):
        self.sync([self.row(str(i), doc_id=f'doc{i}', receipt_number=f'CRK{i}', barcode='bad') for i in range(3)])
        rows = self.listing(batch_id=None)['rows']
        selected = rows[:2]
        payload = {'action': 'exclude', 'lines': [{'id': r['id'], 'revision': r['revision']} for r in selected],
                   'note': '普通采购，批量排除'}
        response = self.client.post(self.base+'/actions', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['data']['processed'], 2)
        excluded = self.listing(batch_id=None, state='excluded')['rows']
        self.assertEqual(len(excluded), 2)
        self.assertTrue(all(r['note'] == payload['note'] for r in excluded))
        self.assertEqual(self.listing(batch_id=None)['total'], 1)
        response = self.client.post(self.base+'/actions', json={
            'action': 'release', 'lines': [{'id': r['id'], 'revision': r['revision']} for r in excluded], 'note': '恢复核对'})
        self.assertEqual(response.status_code, 200, response.text)
        current = self.listing(batch_id=None)['rows']
        stale_payload = {'action': 'exclude', 'lines': [
            {'id': current[0]['id'], 'revision': current[0]['revision']},
            {'id': current[1]['id'], 'revision': current[1]['revision']+1}], 'note': '冲突测试'}
        self.assertEqual(self.client.post(self.base+'/actions', json=stale_payload).status_code, 409)
        self.assertEqual(self.listing(batch_id=None)['total'], 3)
        self.assertEqual(self.listing(batch_id=None, state='excluded')['total'], 0)
        self.db.refresh(self.batch)
        self.assertEqual(self.batch.document, self.document)

    def test_exclude_unmatched_without_target_batch_and_restore(self):
        self.sync([self.row(barcode='NOT-ORDERED')])
        row = self.listing(batch_id=None)['rows'][0]
        self.assertEqual(row['status'], 'pending')
        response = self.client.post(self.base+'/actions', json={
            'action': 'exclude', 'lines': [{'id': row['id'], 'revision': row['revision']}],
            'note': '普通采购，不属于团购'})
        self.assertEqual(response.status_code, 200, response.text)
        excluded = self.listing(batch_id=None, state='excluded')['rows'][0]
        self.assertEqual(excluded['barcode'], 'NOT-ORDERED')
        response = self.client.post(self.base+'/actions', json={
            'action': 'release', 'lines': [{'id': excluded['id'], 'revision': excluded['revision']}],
            'note': '恢复核对'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.listing(batch_id=None)['total'], 1)
        self.db.refresh(self.batch)
        self.assertEqual(self.batch.document, self.document)

    def test_exclude_release_stale_revision_confirmed_orders_and_delete_guards(self):
        self.sync([self.row()]);self.mapping();row=self.listing()['rows'][0]
        self.assertEqual(self.action([row],action='exclude').status_code,200)
        self.assertEqual(self.listing()['total'],0)
        excluded=self.listing(state='excluded')['rows'][0]
        self.assertEqual(self.action([excluded],action='release').status_code,200)
        self.batch.status='confirmed';self.db.commit()
        self.assertEqual(self.action(self.listing()['rows']).status_code,200)
        self.batch.status='draft';self.db.commit()
        response=self.client.request('DELETE',f'/api/v1/group-buy/batches/{self.batch.id}/products/p',json={'revision':1})
        self.assertEqual(response.status_code,409)
        product={k:v for k,v in self.document['products'][0].items() if k in ('code','name','price','abc','pcb')}
        response=self.client.patch(f'/api/v1/group-buy/batches/{self.batch.id}/products/p',json={**product,'barcode':'NEW','revision':1})
        self.assertEqual(response.status_code,409)
        self.assertGreater(self.db.query(InboundAudit).count(),0)

    def test_missing_source_failure_and_sync_scope_do_not_fabricate_arrivals(self):
        self.sync([self.row()]);self.mapping();self.action(self.listing()['rows'])
        self.sync([])
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{})
        self.assertIn('源明细',self.listing()['rows'][0]['reason'])
        with patch.object(service,'load_source',side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):service.sync_source(self.db,None,self.scope,'tester')
        self.assertEqual(self.db.query(InboundLine).count(),1)
        self.assertEqual(self.client.get(self.base+'/lines',params={**self.params,'end_date':'2027-02-01'}).status_code,422)

    def test_supplier_import_allowlisted_fields_leading_zero_and_bad_dimensions(self):
        stream=BytesIO(); book=xlsxwriter.Workbook(stream);sheet=book.add_worksheet('sheet')
        sheet.write_row(0,0,['编号','名称','分类','别名','电话','账号'])
        sheet.write_row(1,0,['0017','兰蔻 上海一百  百联','兰蔻','','private-phone','private-bank'])
        book.close()
        from zipfile import ZipFile, ZIP_DEFLATED
        broken=BytesIO()
        with ZipFile(BytesIO(stream.getvalue())) as src, ZipFile(broken,'w',ZIP_DEFLATED) as dest:
            for item in src.infolist():
                content=src.read(item.filename)
                if item.filename=='xl/worksheets/sheet1.xml':content=content.replace(b'<dimension ref="A1:F2"/>',b'<dimension ref="A1"/>')
                dest.writestr(item,content)
        r=self.client.post(self.base+'/suppliers/import',files={'file':('供应商.xlsx',broken.getvalue())})
        self.assertEqual(r.status_code,200,r.text)
        items=self.client.get(self.base+'/options').json()['data']['suppliers']
        self.assertEqual(items[0]['code'],'0017');self.assertEqual(set(items[0]),{'code','name','category','alias'})
        response=self.client.post(self.base+'/mapping',json={'batch_id':self.batch.id,'revision':1,'source_id':'s','supplier':'兰蔻 上海一百 百联','supplier_code':'0017'})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.post(self.base+'/mapping',json={'batch_id':self.batch.id,'revision':1,'source_id':'s','supplier':'other','supplier_code':'0017'})
        self.assertEqual(response.status_code,422)

    def test_permission_on_all_inbound_routes(self):
        self.user.role.permissions=[]
        for method,url,body in [('GET','/options',None),('GET','/lines',None),('GET',f'/progress/{self.batch.id}',None),
            ('GET','/comparison/1',None),('GET','/history/1',None),('POST','/mapping',{}),('POST','/actions',{}),('POST','/sync',{}),('POST','/suppliers/import',None)]:
            response=self.client.request(method,self.base+url,json=body)
            self.assertEqual(response.status_code,403,(url,response.text))

    def test_source_correction_moves_date_scope_without_duplicate_identity(self):
        self.sync([self.row()]);self.mapping();self.action(self.listing()['rows'])
        scope=InboundScope(start_date=date(2026,11,1),end_date=date(2026,11,30),brand='兰蔻')
        with patch.object(service,'load_source',return_value=[self.row(receipt_time=datetime(2026,11,2))]):
            service.sync_source(self.db,None,scope,'tester')
        self.assertEqual(self.db.query(InboundLine).count(),1)
        self.assertEqual(self.listing()['total'],0)
        self.assertEqual(self.client.get(self.base+f'/progress/{self.batch.id}').json()['data']['received'],{'p:s':6})


if __name__=='__main__':
    unittest.main()
