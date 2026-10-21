"""Local-only, frozen September management-profit review. No online DWD scans."""
import json
from decimal import Decimal
from pathlib import Path
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[3]
D = lambda value: Decimal(str(value or 0))


def summarize(rows, costs, eligible=False):
    sales = sum((D(r['amount']) for r in rows), Decimal(0))
    matched = [r for r in rows if r['code'] in costs]
    cost = sum((D(r['quantity']) * D(costs[r['code']]['price']) for r in matched), Decimal(0))
    complete = len(matched) == len(rows)
    profit = sales - cost if eligible and complete else None
    return dict(net_sales=float(sales), quantity=float(sum((D(r['quantity']) for r in rows), Decimal(0))),
                cost=float(cost) if eligible and complete else None,
                profit=float(profit) if profit is not None else None,
                margin=float(profit / sales * 100) if profit is not None and sales > 0 else None)


def load_snapshot():
    candidates = sorted(p for p in (ROOT / 'outputs').glob('september-profit-separated-*')
                        if (p / 'pending-orders.json').is_file() and (p / 'separation.json').is_file())
    if not candidates:
        raise HTTPException(503, '本地9月试算快照尚未生成')
    folder = candidates[-1]
    read = lambda name: json.loads((folder / name).read_text(encoding='utf-8'))
    report = read('separation.json')
    cost_path = Path(report['cost_snapshot']).resolve()
    if not cost_path.is_relative_to((ROOT / 'outputs').resolve()):
        raise HTTPException(503, '试算成本快照路径无效')
    costs = json.loads(cost_path.read_text(encoding='utf-8'))
    old_rows = json.loads(cost_path.with_name('grouped-source.json').read_text(encoding='utf-8'))
    names = {r['code']: r.get('name') or r['code'] for r in old_rows}
    return folder.name, report, read('grouped-source.json'), read('pending-orders.json'), costs, names


def review_data(kind='', channel='', view='channel', bucket='规则可计算订单', page=1,
                page_size=50, sort_by='profit', sort_order='desc', keyword='', snapshot_data=None):
    snapshot, report, rows, pending, costs, names = snapshot_data or load_snapshot()
    all_rows = rows
    rows = [r for r in rows if (not kind or r['kind'] == kind) and (not channel or r['channel'] == channel)]
    # Classification was frozen for complete orders before any display filters.
    eligible = [r for r in rows if r['bucket'] == '规则可计算订单']
    selected = [r for r in rows if r['bucket'] == bucket and
                (not kind or r['kind'] == kind) and (not channel or r['channel'] == channel)]
    types = [dict(name=k, **summarize([r for r in eligible if r['kind'] == k], costs, True))
             for k in sorted({r['kind'] for r in eligible})]
    if view == 'orders':
        output = []
        for r in pending:
            if channel and r['channel'] != channel:
                continue
            if kind and kind not in r.get('kinds', '').split('|'):
                continue
            reasons = [label for key, label in [('zero_return', '退货金额／退库待核'),
                       ('zero_dispatch', '零金额发货关联收入待核'), ('irregular', '金额数量方向待核'),
                       ('missing_cost', '同时缺成本')] if r[key]]
            output.append(dict(name=r['order_no'] or '缺少订单编号', channel=r['channel'],
                               net_sales=float(D(r['amount'])), quantity=float(D(r['quantity'])),
                               profit=None, cost=None, margin=None, reason='；'.join(reasons)))
    else:
        field = 'channel' if view == 'channel' else 'code'
        groups = {}
        for r in selected:
            groups.setdefault(r[field], []).append(r)
        output = [dict(name=key if field == 'channel' else names.get(key, key), code=key,
                       kind=' / '.join(sorted({r['kind'] for r in items})),
                       reason='' if bucket == '规则可计算订单' else '整单隔离；该组不展示毛利',
                       **summarize(items, costs, bucket == '规则可计算订单')) for key, items in groups.items()]
    if keyword.strip():
        term = keyword.strip().casefold()
        output = [r for r in output if term in str(r.get('name', '')).casefold()
                  or term in str(r.get('code', '')).casefold()]
    valid_sort = sort_by if sort_by in {'name', 'net_sales', 'quantity', 'cost', 'profit', 'margin'} else 'profit'
    present = [r for r in output if r.get(valid_sort) is not None]
    absent = [r for r in output if r.get(valid_sort) is None]
    present.sort(key=lambda r: r[valid_sort], reverse=sort_order == 'desc')
    output = present + absent
    positive = sum((D(r.get('positive_amount')) for r in rows), Decimal(0))
    eligible_positive = sum((D(r.get('positive_amount')) for r in eligible), Decimal(0))
    buckets = []
    for name in ['规则可计算订单', '缺成本订单', '待核订单']:
        items = [r for r in rows if r['bucket'] == name]
        count = None if kind else sum(r['orders'] for r in report['counts'] if r['bucket'] == name and (not channel or r.get('channel') == channel))
        buckets.append(dict(name=name, net_sales=float(sum((D(r['amount']) for r in items), Decimal(0))), orders=count))
    total_net = sum((D(r['amount']) for r in rows), Decimal(0))
    eligible_net = sum((D(r['amount']) for r in eligible), Decimal(0))
    missing_groups = {}
    for r in rows:
        if r['code'] not in costs:
            missing_groups.setdefault(r['code'], []).append(r)
    missing_goods = [dict(code=c, name=names.get(c, c), net_sales=float(sum((D(r['amount']) for r in items), Decimal(0))))
                     for c, items in missing_groups.items()]
    missing_goods.sort(key=lambda r: r['net_sales'], reverse=True)
    pending_scope = [r for r in pending if (not channel or r['channel'] == channel)
                     and (not kind or kind in r.get('kinds', '').split('|'))]
    return dict(month=report.get('month', '2026-09'), snapshot=snapshot, cost_date=report.get('cost_date', '2026-10-20'), tax_basis='含税',
                start_date=report.get('start_date'), end_date=report.get('end_date'), updated_at=report.get('updated_at'), empty=report.get('empty', False),
                requested_end_date=report.get('requested_end_date'), live=report.get('live', False),
                summary=summarize(eligible, costs, True), types=types,
                eligible_share=float(eligible_positive / positive * 100) if positive else None,
                sales_coverage=dict(eligible_net_sales=float(eligible_net), total_net_sales=float(total_net),
                    net_share=float(eligible_net / total_net * 100) if total_net > 0 else None,
                    positive_share=float(eligible_positive / positive * 100) if positive else None),
                repair_summary=dict(missing_skus=len(missing_groups), missing_goods_net_sales=sum(r['net_sales'] for r in missing_goods),
                    top_missing=missing_goods[:10], pending_reasons=[dict(reason=label, orders=sum(bool(r[key]) for r in pending_scope))
                    for key, label in [('zero_return', '零金额退货'), ('zero_dispatch', '零金额发货'), ('irregular', '金额数量方向异常')]]),
                buckets=buckets,
                filtered_summary=summarize(selected, costs, bucket == '规则可计算订单') if view != 'orders' else None,
                rows=output[(page - 1) * page_size:page * page_size], total=len(output),
                channels=sorted({r['channel'] for r in all_rows}), page=page, page_size=page_size)
