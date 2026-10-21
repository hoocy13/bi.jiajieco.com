"""Sales evidence from the existing, reconciled order-level daily ADS."""
from datetime import timedelta
from sqlalchemy import func, select
from fastapi import HTTPException

from app.db.ads import AdsSessionLocal
from app.models.ads import AdsSalesDaily, AdsSalesDailyChannel
from app.services.sales_ads import latest_ready_sales_batch, ensure_batch_covers, AdsDataUnavailable


def load_sales_evidence():
    if AdsSessionLocal is None:
        raise HTTPException(503, '销售预计算未配置')
    with AdsSessionLocal() as db:
        try:
            batch = latest_ready_sales_batch(db)
            end = batch.source_end_date
            start = end - timedelta(days=29)
            previous_end = start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=29)
            ensure_batch_covers(batch, previous_start, end)
        except AdsDataUnavailable as exc:
            raise HTTPException(503, '销售预计算尚未就绪或未覆盖完整对比周期') from exc

        def summary(begin, finish):
            row = db.execute(select(func.sum(AdsSalesDaily.paid_amount),
                func.sum(AdsSalesDaily.orders), func.sum(AdsSalesDaily.quantity)).where(
                AdsSalesDaily.data_version == batch.data_version,
                AdsSalesDaily.sales_date.between(begin, finish))).one()
            amount, orders, quantity = float(row[0] or 0), int(row[1] or 0), float(row[2] or 0)
            return dict(paid_amount=amount, orders=orders, quantity=quantity,
                        avg_order_amount=round(amount / orders, 2) if orders else 0)

        current, previous = summary(start, end), summary(previous_start, previous_end)
        rows = db.execute(select(AdsSalesDailyChannel.channel,
            func.sum(AdsSalesDailyChannel.paid_amount).label('paid_amount'),
            func.sum(AdsSalesDailyChannel.orders).label('orders'),
            func.sum(AdsSalesDailyChannel.quantity).label('quantity')).where(
            AdsSalesDailyChannel.data_version == batch.data_version,
            AdsSalesDailyChannel.sales_date.between(start, end)).group_by(
            AdsSalesDailyChannel.channel).order_by(func.sum(AdsSalesDailyChannel.paid_amount).desc(),
                AdsSalesDailyChannel.channel).limit(8)).mappings().all()
        return {
            'period': '近30天', 'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'scope': '全部销售；仓库筛选仅作用于库存',
            'data_version': batch.data_version,
            'current': {key: round(value, 2) if key != 'orders' else value for key, value in current.items()},
            'previous': dict({key: round(value, 2) if key != 'orders' else value for key, value in previous.items()},
                             start_date=previous_start.isoformat(), end_date=previous_end.isoformat()),
            'change': {f'{field}_rate': round((current[field] - previous[field]) / previous[field] * 100, 2)
                       if previous[field] else None for field in ('paid_amount', 'orders', 'quantity')},
            'top_channels': [dict(channel=r['channel'], paid_amount=round(float(r['paid_amount'] or 0), 2),
                                  orders=int(r['orders'] or 0), quantity=round(float(r['quantity'] or 0), 2)) for r in rows],
        }
