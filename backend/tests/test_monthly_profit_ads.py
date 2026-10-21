from datetime import datetime, date
from decimal import Decimal
from types import SimpleNamespace
import unittest
import gzip
import json
from hashlib import sha256
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch
from app.models.monthly_profit import AdsMonthlyProfitSource, AdsMonthlyProfitSku
from app.services import monthly_profit_ads as ads
from app.services.monthly_profit_source import RULES_VERSION, apply_current_costs, coverage_codes
from app.services.monthly_profit_review import review_data


def signature(*codes):
    return ','.join(code.encode().hex().upper() for code in sorted(codes))


def source_fixture():
    def row(codes, code, quantity, amount, pending=0):
        return dict(coverage=signature(*codes), sku_count=len(codes), pending=pending,
                    code=code, code_key=code, kind='正装', kind_key='type', channel='X', channel_key='X',
                    name=code, name_key=code, quantity=str(quantity), amount=str(amount), positive_amount=str(max(amount, 0)))
    rows = [row(('A', 'B'), 'A', 2, 80), row(('A', 'B'), 'B', 1, 30), row(('A',), 'A', 1, 60), row(('A',), 'A', -1, 0, 1)]
    counts = [dict(coverage=signature('A', 'B'), sku_count=2, pending=0, channel='X', channel_key='X', orders=1),
              dict(coverage=signature('A'), sku_count=1, pending=0, channel='X', channel_key='X', orders=1),
              dict(coverage=signature('A'), sku_count=1, pending=1, channel='X', channel_key='X', orders=1)]
    pending = [dict(coverage=signature('A'), sku_count=1, order_no='R', channel='X', kinds='正装',
                    quantity='-1', amount='0', zero_return=1, zero_dispatch=0, irregular=0)]
    return dict(month='2026-09', start_date='2026-09-01', end_date='2026-09-30',
                requested_end_date='2026-09-30', updated_at='2026-10-01 01:00:00',
                counts=counts, pending=pending, rows=rows, codes=['A', 'B'])


class MonthlySourceTests(unittest.TestCase):
    def test_cost_addition_reclassifies_whole_order_before_filters(self):
        source = source_fixture()
        costs = {'A': {'price': '50', 'id': 1}}
        first = apply_current_costs(source, costs, {'A'}, 'v1')
        isolated = review_data(kind='正装', channel='X', view='product', snapshot_data=first)
        self.assertEqual(isolated['summary']['net_sales'], 60)
        self.assertEqual(isolated['summary']['profit'], 10)
        self.assertEqual(next(b['net_sales'] for b in isolated['buckets'] if b['name'] == '缺成本订单'), 110)
        costs['B'] = {'price': '20', 'id': 2}
        second = apply_current_costs(source, costs, {'A', 'B'}, 'v1')
        complete = review_data(snapshot_data=second)
        self.assertEqual(complete['summary']['net_sales'], 170)
        self.assertEqual(complete['summary']['profit'], 0)
        self.assertEqual(second[3][0]['bucket'], '待核订单')
        self.assertEqual(source, source_fixture())

    def test_price_change_and_delete_do_not_reuse_wrong_profit(self):
        source = source_fixture()
        costs = {'A': {'price': '40', 'id': 3}}
        result = review_data(snapshot_data=apply_current_costs(source, costs, {'A'}, 'v1'))
        self.assertEqual(result['summary']['profit'], 20)
        result = review_data(snapshot_data=apply_current_costs(source, {}, set(), 'v1'))
        self.assertEqual(result['summary']['net_sales'], 0)
        self.assertEqual(result['buckets'][2]['name'], '待核订单')

    def test_hex_coverage_keeps_empty_codes_and_detects_truncation(self):
        self.assertEqual(coverage_codes(signature('', 'SKU,中文'), 2), ('', 'SKU,中文'))
        with self.assertRaises(ValueError):
            coverage_codes(signature('A'), 2)

    def test_round_trip_keeps_decimal_precision_and_checksum(self):
        source = source_fixture()
        source['rows'][0]['amount'] = Decimal('123456789012345.67')
        payload, checksum, size = ads.pack_source(source)
        self.assertEqual(ads.unpack_source(payload, checksum, size)['rows'][0]['amount'], '123456789012345.67')
        with self.assertRaises(ValueError):
            ads.unpack_source(payload+b'x', checksum, size)

    def test_columnar_and_initial_gzip_formats_decode_identically(self):
        source = source_fixture()
        packed, checksum, size = ads.pack_source(source)
        self.assertEqual(ads.unpack_source(packed, checksum, size), source)
        raw = json.dumps(source).encode()
        legacy = gzip.compress(raw)
        self.assertEqual(ads.unpack_source(legacy, sha256(legacy).hexdigest(), len(raw)), source)


class MonthlyAdsReadTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        for model in (AdsPublishBatch, AdsMonthlyProfitSource, AdsMonthlyProfitSku):
            model.__table__.create(self.engine)
        ads._decoded.clear()
        ads._snapshots.clear()

    def tearDown(self):
        self.engine.dispose()

    def publish(self, db, status='ready', version='v1'):
        payload, checksum, size = ads.pack_source(source_fixture())
        db.add(AdsPublishBatch(data_version=version, dataset=ads.DATASET, status=status,
            source_start_date=date(2026,9,1), source_end_date=date(2026,9,30),
            created_at=datetime.now(), published_at=datetime.now()))
        db.add(AdsMonthlyProfitSource(data_version=version, month='2026-09', rules_version=RULES_VERSION,
            code_collation='BINARY', checksum=checksum, raw_bytes=size, payload=payload, created_at=datetime.now()))
        db.add_all([AdsMonthlyProfitSku(data_version=version, product_code=code) for code in ('A','B')])
        db.commit()

    def test_only_ready_versions_and_cost_revision_invalidates_cache(self):
        with Session(self.engine) as db:
            self.publish(db, 'building')
            with self.assertRaises(ads.MonthlySourceNotReady):
                ads.ads_snapshot('2026-09', None, db)
            db.query(AdsPublishBatch).update({'status': 'ready'}); db.commit()
            price = SimpleNamespace(price=Decimal('50'), id=1)
            with patch.object(ads, 'current_prices', return_value={'A': price}):
                before = ads.ads_snapshot('2026-09', None, db)
                self.assertEqual(review_data(snapshot_data=before)['summary']['profit'], 10)
                price.price = Decimal('40'); price.id = 2
                after = ads.ads_snapshot('2026-09', None, db)
                self.assertEqual(review_data(snapshot_data=after)['summary']['profit'], 20)
                self.publish(db, version='v2')
                self.assertEqual(ads.ads_snapshot('2026-09', None, db)[0], 'v2')

    def test_bad_payload_never_falls_back_to_slow_source(self):
        with Session(self.engine) as db:
            self.publish(db)
            db.query(AdsMonthlyProfitSource).update({'checksum': 'wrong'}); db.commit()
            with patch.object(ads, 'current_prices', return_value={}):
                with self.assertRaises(Exception) as error:
                    ads.ads_snapshot('2026-09', None, db)
                self.assertEqual(error.exception.status_code, 503)

    def test_coverage_uses_database_collation_for_aliases(self):
        with Session(self.engine) as db:
            self.publish(db)
            self.assertEqual(ads.matching_codes(db, 'v1', 'NOCASE', {'a': {}}), {'A'})

    def test_unsupported_collation_is_not_executed(self):
        with Session(self.engine) as db:
            with self.assertRaises(ValueError):
                ads.matching_codes(db, 'v1', 'BINARY; DROP TABLE x', {'A': {}})

    def test_pruning_retains_two_ready_versions_per_month(self):
        from app.jobs.build_monthly_profit_ads import prune_month
        from sqlalchemy.orm import sessionmaker
        with Session(self.engine) as db:
            for version in ('v1','v2','v3','other-month'):
                self.publish(db, version=version)
            db.query(AdsMonthlyProfitSource).filter_by(data_version='other-month').update({'month':'2026-08'})
            db.commit()
        with patch('app.jobs.build_monthly_profit_ads.require_sales_profit_build_session_factory', return_value=sessionmaker(bind=self.engine)):
            prune_month('2026-09')
        with Session(self.engine) as db:
            self.assertEqual({r.data_version for r in db.query(AdsMonthlyProfitSource)}, {'v2','v3','other-month'})
            self.assertEqual(db.query(AdsPublishBatch).filter_by(data_version='v1').one().status, 'retired')

    def test_repack_publishes_an_identical_version_and_copies_sku_dimension(self):
        from app.jobs.build_monthly_profit_ads import repack_month
        from sqlalchemy.orm import sessionmaker
        with Session(self.engine) as db:
            self.publish(db)
        with patch('app.jobs.build_monthly_profit_ads.require_sales_profit_build_session_factory', return_value=sessionmaker(bind=self.engine)):
            version = repack_month('2026-09')
        with Session(self.engine) as db:
            self.assertEqual(db.query(AdsMonthlyProfitSku).filter_by(data_version=version).count(), 2)
            row = db.get(AdsMonthlyProfitSource, version)
            self.assertEqual(ads.unpack_source(row.payload, row.checksum, row.raw_bytes), source_fixture())
            self.assertEqual(db.query(AdsPublishBatch).filter_by(data_version=version).one().status, 'ready')
