"""Versioned ADS monthly sources with current-cost classification, no ODS reads."""
from collections import OrderedDict
import gzip
from hashlib import sha256
import json
import lzma
import re
from threading import Lock

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.routers.inventory_valuation import current_prices
from app.models.ads import AdsPublishBatch
from app.models.monthly_profit import AdsMonthlyProfitSource, AdsMonthlyProfitSku
from app.services.monthly_profit_live import month_period, business_today
from app.services.monthly_profit_source import RULES_VERSION, apply_current_costs

DATASET = 'monthly_profit'
MAX_RAW_BYTES = 64 * 1024 * 1024
_decoded = OrderedDict()
_snapshots = OrderedDict()
_lock = Lock()
STRING_FIELDS = frozenset(('coverage', 'code', 'code_key', 'kind', 'kind_key',
                          'channel', 'channel_key', 'name', 'name_key', 'kinds'))


class MonthlySourceNotReady(Exception):
    pass


def pack_source(source):
    # Pool repeated SKU sets, collation weights and labels across all tables.
    # The bounded LZMA dictionary then compresses the compact columnar records.
    strings, indexes, tables = [], {}, {}
    for table in ('counts', 'rows', 'pending'):
        records = source.get(table, [])
        columns = sorted({key for row in records for key in row})
        values = []
        for row in records:
            values_row = []
            for key in columns:
                value = row.get(key)
                if key in STRING_FIELDS and value is not None:
                    if not isinstance(value, str):
                        raise ValueError('Invalid string dimension in monthly source')
                    if value not in indexes:
                        indexes[value] = len(strings)
                        strings.append(value)
                    value = indexes[value]
                values_row.append(value)
            values.append(values_row)
        tables[table] = [columns, values]
    wire = {'format': 'monthly-profit-columnar-v1', 'strings': strings, 'tables': tables,
            'meta': {k: v for k, v in source.items() if k not in tables}}
    raw = json.dumps(wire, ensure_ascii=False, default=str, separators=(',', ':')).encode()
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError('Monthly source exceeds memory budget')
    payload = lzma.compress(raw, preset=6)
    return payload, sha256(payload).hexdigest(), len(raw)


def unpack_source(payload, checksum, raw_bytes):
    if raw_bytes > MAX_RAW_BYTES or sha256(payload).hexdigest() != checksum:
        raise ValueError('Monthly source integrity check failed')
    raw = gzip.decompress(payload) if payload.startswith(b'\x1f\x8b') else lzma.decompress(payload)
    if len(raw) != raw_bytes:
        raise ValueError('Monthly source length check failed')
    wire = json.loads(raw)
    if wire.get('format') != 'monthly-profit-columnar-v1':
        return wire  # Compatible with the initial verified gzip source versions.
    source, strings = wire['meta'], wire['strings']
    for table, (columns, records) in wire['tables'].items():
        source[table] = [{key: strings[value] if key in STRING_FIELDS and value is not None else value
                          for key, value in zip(columns, values)} for values in records]
    return source


def _retain(cache, key, value):
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > 3:
        cache.popitem(last=False)


def matching_codes(ads, version, collation, costs):
    if not re.fullmatch(r'[A-Za-z0-9_]+', collation):
        raise ValueError('Invalid source product collation')
    result = set()
    codes = sorted(costs)
    for start in range(0, len(codes), 500):
        result.update(ads.execute(select(AdsMonthlyProfitSku.product_code).where(
            AdsMonthlyProfitSku.data_version == version,
            AdsMonthlyProfitSku.product_code.collate(collation).in_(codes[start:start+500]),
        )).scalars())
    return result


def ads_snapshot(month, admin, ads):
    month_period(month)
    try:
        manifest = ads.execute(select(
            AdsMonthlyProfitSource.data_version, AdsMonthlyProfitSource.checksum,
            AdsMonthlyProfitSource.raw_bytes, AdsMonthlyProfitSource.code_collation,
        ).join(AdsPublishBatch, AdsPublishBatch.data_version == AdsMonthlyProfitSource.data_version).where(
            AdsMonthlyProfitSource.month == month,
            AdsMonthlyProfitSource.rules_version == RULES_VERSION,
            AdsPublishBatch.dataset == DATASET, AdsPublishBatch.status == 'ready',
        ).order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc()).limit(1)).mappings().first()
        if manifest is None:
            raise MonthlySourceNotReady(month)
        prices = current_prices(admin)
        costs = {code: dict(price=str(row.price), id=row.id) for code, row in prices.items() if row.price > 0}
        fingerprint = sha256(json.dumps(costs, sort_keys=True).encode()).hexdigest()
        source_key = (ads.get_bind(), manifest['data_version'])
        key = (*source_key, fingerprint, str(business_today()))
        # One decoder/classifier for a version. Its work is bounded by the payload
        # budget; concurrent requests never independently fetch the same blob.
        with _lock:
            if key in _snapshots:
                _snapshots.move_to_end(key)
                return _snapshots[key]
            if source_key not in _decoded:
                payload = ads.execute(select(AdsMonthlyProfitSource.payload).where(
                    AdsMonthlyProfitSource.data_version == manifest['data_version'],
                )).scalar_one()
                source = unpack_source(payload, manifest['checksum'], manifest['raw_bytes'])
                if source['month'] != month:
                    raise ValueError('Monthly source period mismatch')
                _retain(_decoded, source_key, source)
            else:
                _decoded.move_to_end(source_key)
            known = matching_codes(ads, manifest['data_version'], manifest['code_collation'], costs)
            snapshot = apply_current_costs(_decoded[source_key], costs, known, manifest['data_version'])
            _retain(_snapshots, key, snapshot)
            return snapshot
    except MonthlySourceNotReady:
        raise
    except (SQLAlchemyError, ValueError, OSError, lzma.LZMAError, KeyError, TypeError, IndexError) as exc:
        raise HTTPException(503, '经营毛利预计算读取失败，请检查已发布数据及权限') from exc
