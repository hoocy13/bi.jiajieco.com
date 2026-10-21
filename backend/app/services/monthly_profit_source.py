"""Cost-independent monthly facts. Only the batch builder reads the source view."""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text

from app.services.monthly_profit_live import month_period, business_today

RULES_VERSION = 'monthly-profit-source-v1'
SIGNATURE_LIMIT = 1_048_576
SOURCE = '`dwd`.`销售单明细账_品牌补全`'


def coverage_codes(signature, expected_count):
    if len(signature) >= SIGNATURE_LIMIT:
        raise ValueError('Order product coverage exceeds the build limit')
    codes = tuple(bytes.fromhex(part).decode('utf-8') for part in signature.split(','))
    if len(codes) != int(expected_count):
        raise ValueError('Truncated order product coverage')
    return codes


def load_month_source(ods, month):
    start, end = month_period(month)
    # A session setting for an aggregate; source tables remain read-only.
    ods.execute(text(f'SET SESSION group_concat_max_len = {SIGNATURE_LIMIT}'))
    params = {'start': start, 'end': end}
    flags = f'''WITH flags AS (
      SELECT `订单编号` order_no,MAX(`销售渠道`) channel,
        GROUP_CONCAT(DISTINCT COALESCE(NULLIF(NULLIF(TRIM(`货品分类`),''),'-1'),'未分类') SEPARATOR '|') kinds,
        GROUP_CONCAT(DISTINCT HEX(TRIM(COALESCE(`货品编号`,''))) ORDER BY HEX(TRIM(COALESCE(`货品编号`,''))) SEPARATOR ',') coverage,
        COUNT(DISTINCT HEX(TRIM(COALESCE(`货品编号`,'')))) sku_count,
        SUM(COALESCE(`分摊后金额`,0)) amount,SUM(COALESCE(`数量`,0)) quantity,
        MAX(CASE WHEN `数量`<0 AND COALESCE(`分摊后金额`,0)=0 THEN 1 ELSE 0 END) zero_return,
        MAX(CASE WHEN `数量`>0 AND COALESCE(`分摊后金额`,0)=0 AND `订单编号`<>'JY202609019123' THEN 1 ELSE 0 END) zero_dispatch,
        MAX(CASE WHEN (`数量`<0 AND `分摊后金额`>0) OR (`数量`>0 AND `分摊后金额`<0)
          OR (COALESCE(`数量`,0)=0 AND COALESCE(`分摊后金额`,0)<>0) THEN 1 ELSE 0 END) irregular
      FROM {SOURCE} WHERE `下单时间`>=:start AND `下单时间`<:end GROUP BY `订单编号`
    ), orders AS (
      SELECT *,CASE WHEN order_no IS NULL OR TRIM(order_no)='' OR zero_return=1 OR zero_dispatch=1 OR irregular=1
        THEN 1 ELSE 0 END pending FROM flags
    )'''
    meta = dict(ods.execute(text(f'''
      SELECT MAX(`updatetime`) updated_at,MAX(DATE(`下单时间`)) last_day,
        COALESCE(SUM(`分摊后金额`),0) amount,COALESCE(SUM(`数量`),0) quantity,
        COUNT(DISTINCT `订单编号`)+COALESCE(MAX(`订单编号` IS NULL),0) orders
      FROM {SOURCE} WHERE `下单时间`>=:start AND `下单时间`<:end
    '''), params).mappings().one())
    counts = [dict(r) for r in ods.execute(text(flags + '''
      SELECT grouped.*,HEX(WEIGHT_STRING(channel)) channel_key FROM (
        SELECT pending,coverage,sku_count,channel,COUNT(*) orders
        FROM orders GROUP BY pending,coverage,sku_count,channel
      ) grouped
    '''), params).mappings()]
    pending = [dict(r) for r in ods.execute(text(flags + '''
      SELECT order_no,channel,kinds,coverage,sku_count,amount,quantity,zero_return,zero_dispatch,irregular
      FROM orders WHERE pending=1 ORDER BY order_no
    '''), params).mappings()]
    rows = [dict(r) for r in ods.execute(text(flags + f'''
      SELECT grouped.*,HEX(WEIGHT_STRING(code)) code_key,HEX(WEIGHT_STRING(kind)) kind_key,
        HEX(WEIGHT_STRING(channel)) channel_key,HEX(WEIGHT_STRING(name)) name_key
      FROM (
        SELECT f.pending,f.coverage,f.sku_count,TRIM(COALESCE(d.`货品编号`,'')) code,
          MAX(d.`货品名称`) name,COALESCE(NULLIF(NULLIF(TRIM(d.`货品分类`),''),'-1'),'未分类') kind,
          COALESCE(NULLIF(TRIM(d.`销售渠道`),''),'未归类') channel,
          SUM(COALESCE(d.`数量`,0)) quantity,SUM(COALESCE(d.`分摊后金额`,0)) amount,
          SUM(CASE WHEN d.`分摊后金额`>0 THEN d.`分摊后金额` ELSE 0 END) positive_amount
        FROM {SOURCE} d JOIN orders f ON d.`订单编号`<=>f.order_no
        WHERE d.`下单时间`>=:start AND d.`下单时间`<:end
        GROUP BY f.pending,f.coverage,f.sku_count,code,kind,COALESCE(NULLIF(TRIM(d.`销售渠道`),''),'未归类')
      ) grouped
    '''), params).mappings()]
    all_codes = set()
    for row in [*counts, *pending, *rows]:
        all_codes.update(coverage_codes(row['coverage'], row['sku_count']))
    if any(len(code) > 255 for code in all_codes):
        raise ValueError('Product code exceeds the ADS dimension length')
    if sum(Decimal(str(r['amount'])) for r in rows) != Decimal(str(meta['amount'])):
        raise ValueError('Source amount reconciliation failed')
    if sum(Decimal(str(r['quantity'])) for r in rows) != Decimal(str(meta['quantity'])):
        raise ValueError('Source quantity reconciliation failed')
    if sum(int(r['orders']) for r in counts) != int(meta['orders']):
        raise ValueError('Order reconciliation failed')
    return dict(month=month, start_date=str(start), requested_end_date=str(end-timedelta(days=1)),
                end_date=str(meta['last_day']) if meta['last_day'] else None,
                updated_at=str(meta['updated_at']) if meta['updated_at'] else None,
                counts=counts, pending=pending, rows=rows, codes=sorted(all_codes))


def apply_current_costs(source, costs, known_codes, version):
    """Classify complete orders before applying any UI filters."""
    coverage = {}
    def missing(row):
        key = row['coverage']
        if key not in coverage:
            coverage[key] = not set(coverage_codes(key, row['sku_count'])).issubset(known_codes)
        return coverage[key]
    def bucket(row):
        return '待核订单' if int(row['pending']) else '缺成本订单' if missing(row) else '规则可计算订单'
    counts = {}
    for row in source['counts']:
        category = bucket(row)
        key = (category, row['channel_key'])
        item = counts.setdefault(key, dict(bucket=category, channel=row['channel'], orders=0))
        item['orders'] += int(row['orders'])
    grouped = {}
    for row in source['rows']:
        category = bucket(row)
        key = (category, row['code_key'], row['kind_key'], row['channel_key'])
        item = grouped.setdefault(key, dict(bucket=category, code=row['code'], kind=row['kind'],
            channel=row['channel'], name=row['name'], name_key=row['name_key'],
            quantity=Decimal(0), amount=Decimal(0), positive_amount=Decimal(0)))
        for field in ('quantity', 'amount', 'positive_amount'):
            item[field] += Decimal(str(row[field]))
        if (row['name_key'] or '') > (item['name_key'] or ''):
            item['name'], item['name_key'] = row['name'], row['name_key']
    rows = list(grouped.values())
    for row in rows:
        row.pop('name_key')
    pending = []
    for row in source['pending']:
        item = {k: v for k, v in row.items() if k not in ('coverage', 'sku_count')}
        for flag in ('zero_return', 'zero_dispatch', 'irregular'):
            item[flag] = int(item[flag])
        item.update(bucket='待核订单', missing_cost=int(missing(row)))
        pending.append(item)
    report = {key: source[key] for key in ('month', 'start_date', 'end_date', 'requested_end_date', 'updated_at')}
    report.update(counts=list(counts.values()), buckets={}, eligible_positive_sales_share=0,
                  cost_date=str(business_today()), empty=not rows, live=True)
    names = source.get('names') or {r['code']: r['name'] or r['code'] for r in rows}
    return (version, report, rows, pending, costs, names)
