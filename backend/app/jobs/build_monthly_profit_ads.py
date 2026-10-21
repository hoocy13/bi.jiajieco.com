"""Publish reconciled, cost-independent month sources; never run in an API request."""
import argparse
from datetime import date, datetime, timedelta, UTC
from hashlib import sha256
import json
import math
import re
from uuid import uuid4

from sqlalchemy import delete, insert, select, text, literal
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.ods import create_ods_engine
from app.db.sales_profit import require_sales_profit_build_session_factory
from app.db.session import SessionLocal
from app.models.ads import AdsPublishBatch
from app.models.monthly_profit import AdsMonthlyProfitSource, AdsMonthlyProfitSku
from app.api.routers.inventory_valuation import current_prices
from app.services.monthly_profit_ads import DATASET, pack_source, unpack_source
from app.services.monthly_profit_source import RULES_VERSION, load_month_source, apply_current_costs
from app.services.monthly_profit_live import month_period, business_today, _load_snapshot
from app.services.monthly_profit_review import review_data


def initialize_schema():
    engine = require_sales_profit_build_session_factory().kw['bind']
    for model in (AdsPublishBatch, AdsMonthlyProfitSource, AdsMonthlyProfitSku):
        model.__table__.create(engine, checkfirst=True)


def _ordered(value):
    if isinstance(value, dict):
        return {k: _ordered(v) for k, v in value.items() if k != 'snapshot'}
    if isinstance(value, list):
        values = [_ordered(v) for v in value]
        return sorted(values, key=lambda v: str(v.get('code', v.get('name', v.get('reason', '')))) if isinstance(v, dict) else str(v))
    return value


def equivalent(left, right):
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(equivalent(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
    if isinstance(left, float) or isinstance(right, float):
        return isinstance(left, (int, float)) and isinstance(right, (int, float)) and math.isclose(left, right, rel_tol=0, abs_tol=1e-6)
    return left == right


def reconcile(source, reference, known, version):
    # A SKU may have several source labels. Retain the existing reference label
    # for display; it carries no prices or cost-dependent classifications.
    source['names'] = reference[5]
    candidate = apply_current_costs(source, reference[4], known, version)
    filters = [{}, {'kind': '正装', 'view': 'product'},
               {'kind': '小样', 'view': 'product', 'bucket': '缺成本订单'},
               {'view': 'orders', 'bucket': '待核订单'}]
    for params in filters:
        before = _ordered(review_data(snapshot_data=reference, page_size=1_000_000, **params))
        after = _ordered(review_data(snapshot_data=candidate, page_size=1_000_000, **params))
        if not equivalent(before, after):
            fields = [key for key in before if not equivalent(before[key], after.get(key))]
            raise ValueError('Monthly reconciliation failed: '+','.join(fields))


def build_month(month):
    start, end = month_period(month)
    factory = require_sales_profit_build_session_factory()
    version = 'monthly-profit-'+month.replace('-', '')+'-'+uuid4().hex
    created = datetime.now(UTC).replace(tzinfo=None)
    with factory() as writer:
        batch = AdsPublishBatch(data_version=version, dataset=DATASET, status='building',
            source_start_date=start, source_end_date=end-timedelta(days=1), created_at=created)
        writer.add(batch); writer.commit()
        batch_id = batch.id
    engine = None
    try:
        engine = create_ods_engine(settings.ODS_DATABASE_URL, settings.ODS_BUILD_READ_TIMEOUT_SECONDS)
        with Session(engine.execution_options(isolation_level='REPEATABLE READ')) as ods, SessionLocal() as admin:
            ods.execute(text('SET TRANSACTION READ ONLY'))
            print(f'[monthly-profit-ads] month={month} stage=source', flush=True)
            source = load_month_source(ods, month)
            collation = ods.execute(text("SELECT COLLATION_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='dwd' AND TABLE_NAME='销售单明细账_品牌补全' AND COLUMN_NAME='货品编号'")).scalar_one()
            if not collation or not re.fullmatch('[A-Za-z0-9_]+', collation):
                raise ValueError('Source product collation unavailable')
            prices = current_prices(admin)
            costs = {k: dict(price=str(v.price), id=v.id) for k, v in prices.items() if v.price > 0}
            fingerprint = sha256(json.dumps(costs, sort_keys=True).encode()).hexdigest()
            print(f'[monthly-profit-ads] month={month} stage=reference', flush=True)
            reference = _load_snapshot(month, start, end, costs, fingerprint, ods)
            # Use the source collation for exactly the same coverage test as the
            # original SQL IN predicate, including case/accent equivalence.
            known = set()
            codes = sorted(costs)
            from sqlalchemy import bindparam
            for offset in range(0, len(codes), 500):
                known.update(ods.execute(text(f"SELECT DISTINCT BINARY TRIM(COALESCE(`货品编号`,'')) code FROM `dwd`.`销售单明细账_品牌补全` WHERE `下单时间`>=:start AND `下单时间`<:end AND TRIM(COALESCE(`货品编号`,'')) IN :codes").bindparams(bindparam('codes', expanding=True)),
                    {'start': start, 'end': end, 'codes': codes[offset:offset+500]}).scalars())
            known = {value.decode('utf-8') if isinstance(value, bytes) else value for value in known}
            reconcile(source, reference, known, version)
        payload, checksum, raw_bytes = pack_source(source)
        with factory() as writer:
            writer.add(AdsMonthlyProfitSource(data_version=version, month=month, rules_version=RULES_VERSION,
                code_collation=collation, checksum=checksum, raw_bytes=raw_bytes, payload=payload, created_at=created))
            for offset in range(0, len(source['codes']), 500):
                writer.execute(insert(AdsMonthlyProfitSku), [{'data_version': version, 'product_code': code} for code in source['codes'][offset:offset+500]])
            batch = writer.get(AdsPublishBatch, batch_id)
            batch.status = 'ready'
            batch.daily_row_count = len(source['rows'])
            batch.channel_row_count = len(source['counts'])
            batch.reconciliation = {'rules_version': RULES_VERSION, 'strict_mismatches': [],
                'source_updated_at': source['updated_at'], 'sku_count': len(source['codes']),
                'raw_bytes': raw_bytes, 'compressed_bytes': len(payload)}
            batch.finished_at = batch.published_at = datetime.now(UTC).replace(tzinfo=None)
            writer.commit()
        print(f'[monthly-profit-ads] month={month} stage=ready raw_bytes={raw_bytes} compressed_bytes={len(payload)}', flush=True)
        return version
    except Exception as exc:
        with factory() as writer:
            batch = writer.get(AdsPublishBatch, batch_id)
            batch.status = 'failed'; batch.error_code = type(exc).__name__
            batch.finished_at = datetime.now(UTC).replace(tzinfo=None)
            writer.commit()
        raise
    finally:
        if engine is not None:
            engine.dispose()


def repack_month(month):
    """Re-encode an already reconciled source without rescanning business data."""
    with require_sales_profit_build_session_factory()() as db:
        previous = db.execute(select(AdsMonthlyProfitSource).join(AdsPublishBatch,
            AdsPublishBatch.data_version == AdsMonthlyProfitSource.data_version).where(
                AdsPublishBatch.dataset == DATASET, AdsPublishBatch.status == 'ready',
                AdsMonthlyProfitSource.month == month, AdsMonthlyProfitSource.rules_version == RULES_VERSION,
            ).order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc()).limit(1)).scalar_one()
        source = unpack_source(previous.payload, previous.checksum, previous.raw_bytes)
        payload, checksum, size = pack_source(source)
        if source != unpack_source(payload, checksum, size):
            raise ValueError('Repacked monthly source differs from verified input')
        old_batch = db.execute(select(AdsPublishBatch).where(AdsPublishBatch.data_version == previous.data_version)).scalar_one()
        version = 'monthly-profit-'+month.replace('-', '')+'-'+uuid4().hex
        now = datetime.now(UTC).replace(tzinfo=None)
        db.add(AdsMonthlyProfitSource(data_version=version, month=month, rules_version=RULES_VERSION,
            code_collation=previous.code_collation, checksum=checksum, raw_bytes=size, payload=payload, created_at=now))
        db.execute(insert(AdsMonthlyProfitSku).from_select(['data_version', 'product_code'],
            select(literal(version), AdsMonthlyProfitSku.product_code).where(AdsMonthlyProfitSku.data_version == previous.data_version)))
        db.add(AdsPublishBatch(data_version=version, dataset=DATASET, status='ready',
            source_start_date=old_batch.source_start_date, source_end_date=old_batch.source_end_date,
            daily_row_count=old_batch.daily_row_count, channel_row_count=old_batch.channel_row_count,
            created_at=now, finished_at=now, published_at=now,
            reconciliation={**(old_batch.reconciliation or {}), 'repacked_from': previous.data_version,
                            'raw_bytes': size, 'compressed_bytes': len(payload)}))
        db.commit()
        print(f'[monthly-profit-ads] month={month} stage=repacked raw_bytes={size} compressed_bytes={len(payload)}', flush=True)
        return version


def prune_month(month):
    with require_sales_profit_build_session_factory()() as db:
        versions = db.execute(select(AdsPublishBatch).join(AdsMonthlyProfitSource,
            AdsPublishBatch.data_version == AdsMonthlyProfitSource.data_version).where(
                AdsPublishBatch.dataset == DATASET, AdsPublishBatch.status == 'ready',
                AdsMonthlyProfitSource.month == month,
            ).order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc())).scalars().all()
        for batch in versions[2:]:
            db.execute(delete(AdsMonthlyProfitSku).where(AdsMonthlyProfitSku.data_version == batch.data_version))
            db.execute(delete(AdsMonthlyProfitSource).where(AdsMonthlyProfitSource.data_version == batch.data_version))
            batch.status = 'retired'; db.commit()


def main():
    parser = argparse.ArgumentParser(description='Precompute monthly management-profit sources')
    parser.add_argument('--month', action='append')
    parser.add_argument('--initialize-only', action='store_true')
    parser.add_argument('--prune', action='store_true')
    parser.add_argument('--repack-only', action='store_true', help='Re-encode verified sources, without reading ODS')
    args = parser.parse_args()
    try:
        initialize_schema()
        if args.initialize_only:
            print('Monthly-profit schema initialized'); return
        today = business_today()
        months = args.month or [today.strftime('%Y-%m'), (today.replace(day=1)-timedelta(days=1)).strftime('%Y-%m')]
        for month in dict.fromkeys(months):
            repack_month(month) if args.repack_only else build_month(month)
            if args.prune:
                prune_month(month)
    except Exception as exc:
        # A SQLAlchemy traceback could include a business-data payload.
        print(f'[monthly-profit-ads] stage=failed error={type(exc).__name__}', flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
