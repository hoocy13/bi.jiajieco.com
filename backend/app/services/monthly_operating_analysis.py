"""Read-only, version-pinned operating analysis frozen into monthly artifacts."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import text


def dec(value):
    return Decimal(str(value or 0))


def changes(rows, current, previous):
    buckets = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in rows:
        buckets[row['key']][0 if row['period'] == current else 1] += dec(row['paid_amount'])
    result = []
    for key, (amount, base) in buckets.items():
        result.append(dict(name=key, paid_amount=float(amount), previous_amount=float(base),
                           change=float(amount-base), mom=float(amount/base-1) if base > 0 else None))
    return sorted(result, key=lambda r: (-r['change'], r['name']))


def inventory_analysis(sales, stock, days):
    """Join only stable nonempty SKU codes; keep zero/negative net sales explicit."""
    sold, held, names = defaultdict(Decimal), defaultdict(Decimal), {}
    missing_sales = Decimal(0)
    for row in sales:
        code = str(row.get('product_code') or '').strip()
        if not code or code == '-':
            missing_sales += dec(row['quantity'])
            continue
        sold[code] += dec(row['quantity'])
        names[code] = row.get('product') or code
    for row in stock:
        code = str(row.get('product_code') or '').strip()
        if not code or code == '-':
            continue
        held[code] += dec(row['stock'])
        names.setdefault(code, row.get('product') or code)
    rows = []
    unmatched = sold.keys() - held.keys()
    for code in sorted(held.keys()):
        quantity, units = sold[code], held[code]
        if units < 0:
            kind = '库存异常'
        elif quantity < 0:
            kind = '净退货'
        elif quantity == 0 and units > 0:
            kind = '本月无净动销'
        elif quantity > 0 and units / (quantity / days) < 15:
            kind = '库存偏少'
        elif quantity > 0 and units / (quantity / days) > 90:
            kind = '库存偏多'
        else:
            continue
        rows.append(dict(product_code=code, product=names[code], stock=float(units),
                         quantity=float(quantity), days=float(units/quantity*days) if quantity > 0 and units >= 0 else None,
                         signal=kind))
    low = sorted((r for r in rows if r['signal']=='库存偏少'), key=lambda r:(r['days'],-r['quantity'],r['product_code']))
    high = sorted((r for r in rows if r['signal'] in ('库存偏多','本月无净动销')), key=lambda r:(-r['stock'],r['product_code']))
    return dict(low=low[:5], high=high[:5], low_count=len(low), high_count=len(high),
                exception_count=sum(r['signal'] in ('库存异常','净退货') for r in rows),
                missing_code_sales_quantity=float(missing_sales), unmatched_sales_skus=len(unmatched),
                unmatched_sales_quantity=float(sum((sold[c] for c in unmatched), Decimal(0))))


def build_operating_analysis(ads, ods, artifact, month, version):
    start = date.fromisoformat(month+'-01')
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
    previous = (start-timedelta(days=1)).replace(day=1)
    params = dict(v=version, start=previous, end=end, current=start)
    # Do not substitute a newer sales version when the frozen report is no longer retained.
    totals = [dict(r) for r in ads.execute(text('''
        SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS period,
               SUM(`paid_amount`) AS paid_amount, SUM(`quantity`) AS quantity
        FROM `ads_sales_daily` WHERE `data_version`=:v AND `sales_date` BETWEEN :start AND :end
        GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m')
    '''),params).mappings()]
    if {r['period'] for r in totals} != {month,previous.isoformat()[:7]}:
        raise ValueError('月报原销售版本的本月或上月数据不可用，停止扩展')
    periods = sorted(artifact['snapshot']['datasets']['periods'],key=lambda r:r['sort_order'])[-2:]
    for actual, expected in zip(sorted(totals,key=lambda r:r['period']),periods):
        if abs(dec(actual['paid_amount'])-dec(expected['paid_amount'])) > Decimal('0.01'):
            raise ValueError('月报冻结总额与ADS不一致，停止扩展')
    rows = [dict(r) for r in ads.execute(text('''
        SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS period, `channel`, `brand`, `product`, `product_type`,
               SUM(`paid_amount`) AS paid_amount, SUM(`quantity`) AS quantity
        FROM `ads_sales_daily_brand_channel_product`
        WHERE `data_version`=:v AND `sales_date` BETWEEN :start AND :end
        GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m'), `channel`, `brand`, `product`, `product_type`
    '''),params).mappings()]
    current_rows = [r for r in rows if r['period']==month]
    current_amount = sum((dec(r['paid_amount']) for r in current_rows),Decimal(0))
    detail_totals = [dict(r) for r in ads.execute(text('''
        SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS period, SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_detail_daily_scope` WHERE `data_version`=:v AND `product_type_scope`='all'
          AND `sales_date` BETWEEN :start AND :end GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m')
    '''),params).mappings()]
    for total in detail_totals:
        amount=sum((dec(r['paid_amount']) for r in rows if r['period']==total['period']),Decimal(0))
        if abs(amount-dec(total['paid_amount']))>Decimal('0.01'):
            raise ValueError('品牌渠道商品汇总与全分类明细金额不一致')
    if len(detail_totals)!=2:
        raise ValueError('缺少销售明细核对基准')
    brand_changes=changes([dict(r,key=r['brand']) for r in rows],month,previous.isoformat()[:7])
    channels=changes([dict(r,key=r['channel']) for r in rows],month,previous.isoformat()[:7])
    drivers=[]
    for channel in sorted(channels,key=lambda r:-abs(r['change']))[:3]:
        subset=[r for r in rows if r['channel']==channel['name']]
        brands=changes([dict(r,key=r['brand']) for r in subset],month,previous.isoformat()[:7])
        products=changes([dict(r,key=r['brand']+' · '+r['product']+'（'+r['product_type']+'）') for r in subset],month,previous.isoformat()[:7])
        drivers.append(dict(**channel,brands=sorted(brands,key=lambda r:-abs(r['change']))[:3],
                            products=sorted(products,key=lambda r:-abs(r['change']))[:3]))
    matrix=[]
    for brand in sorted(brand_changes,key=lambda r:-r['paid_amount'])[:5]:
        subset=[r for r in rows if r['brand']==brand['name']]
        channel_changes=changes([dict(r,key=r['channel']) for r in subset],month,previous.isoformat()[:7])
        positive=[r for r in channel_changes if r['paid_amount']>0]
        largest=max(positive,key=lambda r:r['paid_amount']) if positive else None
        gains=[r for r in channel_changes if r['change']>0]
        losses=[r for r in channel_changes if r['change']<0]
        matrix.append(dict(**brand,top_channel=largest['name'] if largest else '-',
                           top_share=largest['paid_amount']/brand['paid_amount'] if largest and brand['paid_amount']>0 else None,
                           growth=gains[0] if gains else None,decline=losses[-1] if losses else None,
                           channels=sorted(channel_changes,key=lambda r:-r['paid_amount'])))
    result=dict(schema_version=1,month=month,sales_version=version,detail_amount=float(current_amount),
                headline_gap=float(current_amount-dec(next(r['paid_amount'] for r in totals if r['period']==month))),
                drivers=drivers,brands=matrix,
                sources=['ads_sales_daily','ads_sales_daily_brand_channel_product','ads_sales_detail_daily_scope','ads_sales_brand_turnover_item','ods.历史库存','ods.历史库存快照批次'])
    trend_start = (previous-timedelta(days=1)).replace(day=1)
    trend_params = dict(v=version, start=trend_start, end=end)
    trend_totals = [dict(r) for r in ads.execute(text("""
        SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS month, COUNT(*) AS day_count,
               SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_daily` WHERE `data_version`=:v AND `sales_date` BETWEEN :start AND :end
        GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m') ORDER BY month
    """),trend_params).mappings()]
    import calendar
    months = [r['month'] for r in trend_totals]
    if len(months) != 3 or any(r['day_count'] != calendar.monthrange(int(r['month'][:4]),int(r['month'][5:]))[1] for r in trend_totals):
        raise ValueError('连续三个月销售数据不完整，停止生成趋势图')
    channel_months = [dict(r) for r in ads.execute(text("""
        SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS month, `channel`, SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_daily_channel` WHERE `data_version`=:v AND `sales_date` BETWEEN :start AND :end
        GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m'), `channel`
    """),trend_params).mappings()]
    for total in trend_totals:
        if abs(sum((dec(r['paid_amount']) for r in channel_months if r['month']==total['month']),Decimal(0))-dec(total['paid_amount']))>Decimal('0.01'):
            raise ValueError('三个月渠道合计与公司销售额不一致')
    result['channel_trends'] = dict(months=months, selection='本月增减额绝对值前三渠道',
        series=[dict(name=d['name'],values=[float(next((r['paid_amount'] for r in channel_months if r['month']==m and r['channel']==d['name']),0)) for m in months]) for d in drivers])
    from app.services.brand_inventory_flow import (
        load_brand_inventory_flow_source, build_brand_inventory_flow, month_sequence, previous_month_end,
    )
    flow_start = start.replace(month=1)
    expected_dates = {previous_month_end(flow_start), *[
        date(m.year,m.month,calendar.monthrange(m.year,m.month)[1]) for m in month_sequence(flow_start,end)
    ]}
    flows = []
    for brand_row in matrix:
        brand = brand_row['name']
        source = load_brand_inventory_flow_source(ods,start_date=flow_start,end_date=end,brand=brand,include_sales=False)
        complete_dates = {r['snapshot_date'] for r in source['batches'] if str(r['status']).upper()=='SUCCESS'}
        if not expected_dates.issubset(complete_dates):
            raise ValueError(f'{brand}进销存缺少成功月末快照，停止生成')
        # Match BI dimensions but pin sales to the report's original ADS version.
        source['sales'] = [dict(r) for r in ads.execute(text("""
            SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS month_key, '全部仓库' AS warehouse, `product_type`,
                   SUM(`quantity`) AS sales_quantity, SUM(`paid_amount`) AS sales_amount
            FROM `ads_sales_daily_brand_channel_product` WHERE `data_version`=:v
              AND `brand`=:brand AND `sales_date` BETWEEN :start AND :end
            GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m'), `product_type`
        """),dict(v=version,brand=brand,start=flow_start,end=end)).mappings()]
        monthly_check = [dict(r) for r in ads.execute(text("""
            SELECT DATE_FORMAT(`sales_date`, '%Y-%m') AS month_key,
                   SUM(`quantity`) AS quantity, SUM(`paid_amount`) AS paid_amount
            FROM `ads_sales_daily_brand_scope` WHERE `data_version`=:v AND `brand`=:brand
              AND `sales_date` BETWEEN :start AND :end AND `product_type_scope`='selected'
            GROUP BY DATE_FORMAT(`sales_date`, '%Y-%m')
        """),dict(v=version,brand=brand,start=flow_start,end=end)).mappings()]
        for m in monthly_check:
            selected = [r for r in source['sales'] if r['month_key']==m['month_key'] and r['product_type'] in ('正装','小样')]
            for source_field,check_field in (('sales_quantity','quantity'),('sales_amount','paid_amount')):
                if abs(sum((dec(r[source_field]) for r in selected),Decimal(0))-dec(m[check_field]))>Decimal('0.01'):
                    raise ValueError(f'{brand}进销存销售与品牌汇总不一致')
        data = build_brand_inventory_flow(source,start_date=flow_start,end_date=end,brand=brand,
                                          product_types=('正装','小样'))
        # No assumption that purchase/sales explain all transfers and adjustments.
        for row in data['months']:
            row['other_change'] = row['ending_quantity']-row['opening_quantity']-row['inbound_quantity']+row['sales_quantity']
        segments = {}
        for kind, product_type in (('full_size','正装'),('sample','小样')):
            segment = build_brand_inventory_flow(source,start_date=flow_start,end_date=end,brand=brand,
                                                  product_types=(product_type,))
            segments[kind] = dict(months=segment['months'],summary=segment['summary'])
        for i, combined in enumerate(data['months']):
            for field in ('opening_quantity','inbound_quantity','sales_quantity','ending_quantity'):
                if abs(sum((dec(segment['months'][i][field]) for segment in segments.values()),Decimal(0))-dec(combined[field]))>Decimal('0.01'):
                    raise ValueError(f'{brand}正装小样合计与总图不一致')
        flows.append(dict(brand=brand,months=data['months'],summary=data['summary'],segments=segments))
    result['brand_flows'] = dict(start_date=flow_start.isoformat(),end_date=end.isoformat(),
        product_types=['正装','小样'],selection='本月全分类净销售额前五品牌',brands=flows)
    completed=ods.execute(text("SELECT COUNT(*) FROM `历史库存快照批次` WHERE `快照日期`=:day AND UPPER(COALESCE(`状态`,''))='SUCCESS'"),dict(day=end)).scalar()
    if not completed:
        result['inventory']=dict(available=False,reason='缺少成功的月末库存快照')
        return result
    stock=[dict(r) for r in ods.execute(text('''
        SELECT TRIM(`货品编号`) AS product_code, MAX(`货品名称`) AS product, SUM(COALESCE(`库存量`,0)) AS stock
        FROM `历史库存` WHERE `快照日期`=:day GROUP BY TRIM(`货品编号`)
    '''),dict(day=end)).mappings()]
    frozen_inventory=artifact['snapshot']['datasets'].get('inventory_snapshots',[])
    original=next((r for r in frozen_inventory if r.get('snapshot_date')==end.isoformat()),None)
    if original is None or abs(sum((dec(r['stock']) for r in stock),Decimal(0))-dec(original['stock_quantity']))>Decimal('0.01'):
        raise ValueError('月末库存快照与原月报不一致，停止扩展')
    sales=[dict(r) for r in ads.execute(text('''
        SELECT TRIM(`product_code`) AS product_code, MAX(`product`) AS product,
               SUM(`quantity`) AS quantity, SUM(`paid_amount`) AS paid_amount
        FROM `ads_sales_brand_turnover_item` WHERE `data_version`=:v
          AND `sales_date` BETWEEN :current AND :end GROUP BY TRIM(`product_code`)
    '''),params).mappings()]
    if abs(sum((dec(r['paid_amount']) for r in sales),Decimal(0))-current_amount)>Decimal('0.01'):
        result['inventory']=dict(available=False,reason='商品编码销售汇总未与月报明细对齐，暂不联动')
    else:
        result['inventory']=dict(available=True,snapshot_date=end.isoformat(),stock_basis='月末库存量（非可用库存）',
                                 **inventory_analysis(sales,stock,end.day))
    return result
