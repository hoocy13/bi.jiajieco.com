"""Read-only month-level review, cached before display filtering."""
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from json import dumps
from threading import Lock
from time import monotonic
from sqlalchemy import text
from fastapi import HTTPException
from app.api.routers.inventory_valuation import current_prices

_cache = {}
_lock = Lock()


def month_period(month, today=None):
    today = today or date.today()
    try:
        start = date.fromisoformat(month + '-01')
    except ValueError as exc:
        raise HTTPException(422, '月份格式应为YYYY-MM') from exc
    if start > today:
        raise HTTPException(422, '不能查询未来月份')
    following = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, min(following, today + timedelta(days=1))


def live_snapshot(month, admin, ods):
    start, end = month_period(month)
    prices = current_prices(admin)
    costs = {k: dict(price=str(v.price), id=v.id) for k, v in prices.items() if v.price > 0}
    fingerprint = sha256(dumps(costs, sort_keys=True).encode()).hexdigest()
    key = (month, end.isoformat(), fingerprint, str(ods.get_bind().url.render_as_string(hide_password=True)))
    with _lock:
        cached = _cache.get(key)
        if cached and cached[0] > monotonic():
            return cached[1]
    params = {'start': start, 'end': end}
    codes = []
    for i, code in enumerate(sorted(costs)):
        params[f'c{i}'] = code
        codes.append(f':c{i}')
    known = "TRIM(COALESCE(`货品编号`,'')) IN (" + ','.join(codes) + ')' if codes else 'FALSE'
    source = '`dwd`.`销售单明细账_品牌补全`'
    cte = f'''WITH flags AS (
      SELECT `订单编号` order_no, MAX(`销售渠道`) channel,
        GROUP_CONCAT(DISTINCT COALESCE(NULLIF(NULLIF(TRIM(`货品分类`),''),'-1'),'未分类') SEPARATOR '|') kinds,
        SUM(COALESCE(`分摊后金额`,0)) amount,SUM(COALESCE(`数量`,0)) quantity,
        MAX(CASE WHEN NOT ({known}) THEN 1 ELSE 0 END) missing_cost,
        MAX(CASE WHEN `数量`<0 AND COALESCE(`分摊后金额`,0)=0 THEN 1 ELSE 0 END) zero_return,
        MAX(CASE WHEN `数量`>0 AND COALESCE(`分摊后金额`,0)=0 AND `订单编号`<>'JY202609019123' THEN 1 ELSE 0 END) zero_dispatch,
        MAX(CASE WHEN (`数量`<0 AND `分摊后金额`>0) OR (`数量`>0 AND `分摊后金额`<0)
          OR (COALESCE(`数量`,0)=0 AND COALESCE(`分摊后金额`,0)<>0) THEN 1 ELSE 0 END) irregular
      FROM {source} WHERE `下单时间`>=:start AND `下单时间`<:end GROUP BY `订单编号`
    ), classified AS (
      SELECT *,CASE WHEN order_no IS NULL OR TRIM(order_no)='' OR zero_return=1 OR zero_dispatch=1 OR irregular=1
        THEN '待核订单' WHEN missing_cost=1 THEN '缺成本订单' ELSE '规则可计算订单' END bucket FROM flags
    )'''
    meta = ods.execute(text(f'''SELECT MAX(`updatetime`) updated, MAX(DATE(`下单时间`)) last_day
        FROM {source} WHERE `下单时间`>=:start AND `下单时间`<:end'''), params).mappings().one()
    counts = [dict(r) for r in ods.execute(text(cte + ''' SELECT bucket,channel,COUNT(*) orders FROM classified GROUP BY bucket,channel'''), params).mappings()]
    pending = [dict(r) for r in ods.execute(text(cte + " SELECT * FROM classified WHERE bucket='待核订单' ORDER BY order_no"), params).mappings()]
    rows = [dict(r) for r in ods.execute(text(cte + f''' SELECT f.bucket,TRIM(COALESCE(d.`货品编号`,'')) code,
        MAX(d.`货品名称`) name,COALESCE(NULLIF(NULLIF(TRIM(d.`货品分类`),''),'-1'),'未分类') kind,
        COALESCE(NULLIF(TRIM(d.`销售渠道`),''),'未归类') channel,
        SUM(COALESCE(d.`数量`,0)) quantity,SUM(COALESCE(d.`分摊后金额`,0)) amount,
        SUM(CASE WHEN d.`分摊后金额`>0 THEN d.`分摊后金额` ELSE 0 END) positive_amount
        FROM {source} d JOIN classified f ON d.`订单编号`<=>f.order_no
        WHERE d.`下单时间`>=:start AND d.`下单时间`<:end
        GROUP BY f.bucket,code,kind,COALESCE(NULLIF(TRIM(d.`销售渠道`),''),'未归类')'''), params).mappings()]
    names = {r['code']: r['name'] or r['code'] for r in rows}
    report = dict(month=month, counts=counts, buckets={}, eligible_positive_sales_share=0,
                  start_date=str(start), end_date=str(meta['last_day']) if meta['last_day'] else None,
                  requested_end_date=str(end - timedelta(days=1)), updated_at=str(meta['updated']) if meta['updated'] else None,
                  cost_date=str(date.today()), empty=not rows, live=True)
    snapshot = (f'monthly-{month}-{fingerprint[:12]}', report, rows, pending, costs, names)
    with _lock:
        _cache.clear() if len(_cache) >= 3 else None
        _cache[key] = (monotonic() + 300, snapshot)
    return snapshot
