from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.ads import AdsPublishBatch
from app.services.sales_sources import is_online_sales_channel


DATASET = "sales_profit"
TABLE = "ads_sales_profit_daily"
MAX_PERIOD_DAYS = 93
MAX_GROUPED_ROWS = 40_000
SORT_FIELDS = {
    "owner", "customer_code", "customer_name", "product_code", "product_name", "brand",
    "product_type", "channel", "channel_type", "quantity", "sale_quantity", "return_quantity",
    "paid_amount", "sale_amount", "return_amount", "avg_price", "core_cost", "estimated_cost",
    "estimated_profit", "margin_rate", "reference_price", "reference_quantity", "price_delta",
    "price_delta_rate", "price_effect_amount", "cost_coverage_rate",
}
NUMERIC_INPUTS = (
    "quantity", "paid_amount", "sale_quantity", "sale_amount", "return_quantity", "return_amount",
)
ZERO = Decimal("0")
_raw_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = Lock()
CACHE_TTL_SECONDS = 120
CACHE_MAX_ROWS = 24_000


@dataclass(frozen=True)
class AnalysisParams:
    view: str = "profit"
    range: str = "month"
    start_date: date | None = None
    end_date: date | None = None
    owner: str = ""
    brand: tuple[str, ...] = ()
    channel_type: str = "all"
    channel: tuple[str, ...] = ()
    product_type: tuple[str, ...] = ("正装", "小样")
    customer_keyword: str = ""
    keyword: str = ""
    group_by: str = "owner"
    benchmark: str = "company"
    price_direction: str = "all"
    cost_status: str = "all"
    page: int = 1
    page_size: int = 50
    sort_by: str = ""
    sort_order: str = "desc"


def decimal(value: object) -> Decimal:
    return ZERO if value is None else Decimal(str(value))


def percent(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    return numerator / denominator * 100 if denominator > 0 else None


def number(value: Decimal | None, places: int = 2) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def date_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def resolve_period(params: AnalysisParams, batch: AdsPublishBatch) -> tuple[date, date, date, date]:
    metadata = batch.reconciliation or {}
    as_of = date_value(metadata.get("max_sales_date") or batch.source_end_date)
    if params.start_date or params.end_date:
        if not params.start_date or not params.end_date:
            raise HTTPException(422, "起止日期需要同时选择")
        start, end = params.start_date, params.end_date
    elif params.range == "custom":
        raise HTTPException(422, "请选择自定义起止日期")
    else:
        start, end = as_of.replace(day=1), as_of
    if start > end:
        raise HTTPException(422, "开始日期不能晚于结束日期")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise HTTPException(422, f"单次最多查询 {MAX_PERIOD_DAYS} 天，请缩小日期范围")
    if start < batch.source_start_date or end > batch.source_end_date or end > as_of:
        raise HTTPException(422, "所选日期超出已发布销售数据范围")
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - (end - start)
    if params.benchmark == "previous" and previous_start < batch.source_start_date:
        raise HTTPException(422, "上期日期超出已发布数据范围，请缩小日期范围或切换参考价")
    return start, end, previous_start, previous_end


def latest_batch(ads: Session) -> AdsPublishBatch:
    try:
        batch = ads.scalars(select(AdsPublishBatch).where(
            AdsPublishBatch.dataset == DATASET, AdsPublishBatch.status == "ready",
        ).order_by(AdsPublishBatch.published_at.desc(), AdsPublishBatch.id.desc()).limit(1)).first()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "销售毛利分析数据尚未就绪，请先发布 sales_profit 数据集") from exc
    if batch is None:
        raise HTTPException(503, "销售毛利分析数据尚未就绪，请先发布 sales_profit 数据集")
    return batch


def load_channel_dimensions(ods: Session) -> dict[str, dict]:
    rows = ods.execute(text("""
        SELECT COALESCE(NULLIF(TRIM(`渠道名称`), ''), '未归类') AS channel,
               MAX(COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配')) AS owner,
               MAX(COALESCE(NULLIF(TRIM(`分类`), ''), '未分类')) AS category,
               MAX(COALESCE(NULLIF(TRIM(`线上平台`), ''), '未设置')) AS platform
        FROM `渠道列表`
        GROUP BY COALESCE(NULLIF(TRIM(`渠道名称`), ''), '未归类')
    """)).mappings().all()
    return {
        str(row["channel"]): {
            "owner": row["owner"],
            "channel_type": "线上" if is_online_sales_channel(
                row["category"], row["platform"], row["channel"],
            ) else "线下",
        }
        for row in rows
    }


def aggregation_sql(params: AnalysisParams, version: str, start: date, end: date,
                    owner_channels: tuple[str, ...] | None = None) -> tuple[str, dict]:
    filters = ["`data_version` = :data_version", "`sales_date` BETWEEN :start_date AND :end_date"]
    values = {"data_version": version, "start_date": start, "end_date": end}
    for field, items in (("brand", params.brand), ("channel", params.channel), ("product_type", params.product_type)):
        items = sorted({item.strip() for item in items if item.strip() and item != "__all__"})
        if items:
            names = []
            for index, item in enumerate(items):
                key = f"{field}_{index}"
                names.append(f":{key}")
                values[key] = item
            filters.append(f"`{field}` IN ({', '.join(names)})")
    if owner_channels is not None:
        names = []
        for index, channel in enumerate(owner_channels):
            key = f"owner_channel_{index}"
            names.append(f":{key}")
            values[key] = channel
        filters.append(f"`channel` IN ({', '.join(names)})")
    if params.keyword.strip():
        filters.append("(INSTR(LOWER(`product_code`), LOWER(:keyword)) > 0 OR INSTR(LOWER(`product_name`), LOWER(:keyword)) > 0)")
        values["keyword"] = params.keyword.strip()
    return f"""
        SELECT `brand`, `channel`, COALESCE(`customer_code`, '') AS customer_code,
               MAX(`customer_name`) AS customer_name, COALESCE(`product_code`, '') AS product_code,
               MAX(`product_name`) AS product_name, `product_type`,
               {', '.join(f'SUM(`{field}`) AS {field}' for field in NUMERIC_INPUTS)}
        FROM `{TABLE}` WHERE {' AND '.join(filters)}
        GROUP BY `brand`, `channel`, COALESCE(`customer_code`, ''),
                 COALESCE(`product_code`, ''), `product_type`
        LIMIT {MAX_GROUPED_ROWS + 1}
    """, values


def load_aggregates(ads: Session, params: AnalysisParams, version: str, start: date, end: date,
                    owner_channels: tuple[str, ...] | None = None) -> list[dict]:
    if owner_channels == ():
        return []
    sql, values = aggregation_sql(params, version, start, end, owner_channels)
    key = (id(ads.get_bind()), tuple(sorted(values.items())))
    now = monotonic()
    with _cache_lock:
        cached = _raw_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        rows = [dict(row) for row in ads.execute(text(sql), values).mappings().all()]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "销售毛利分析数据尚未就绪，请重新发布 sales_profit 数据集") from exc
    if len(rows) > MAX_GROUPED_ROWS:
        raise HTTPException(422, "查询结果过大，请缩小日期或增加品牌、渠道筛选条件")
    if len(rows) <= CACHE_MAX_ROWS:
        with _cache_lock:
            for old_key in [entry for entry, (expires, _) in _raw_cache.items() if expires <= now]:
                _raw_cache.pop(old_key, None)
            while _raw_cache and sum(len(entry[1]) for entry in _raw_cache.values()) + len(rows) > CACHE_MAX_ROWS:
                _raw_cache.pop(min(_raw_cache, key=lambda entry: _raw_cache[entry][0]))
            while len(_raw_cache) >= 32:
                _raw_cache.pop(min(_raw_cache, key=lambda entry: _raw_cache[entry][0]))
            _raw_cache[key] = (now + CACHE_TTL_SECONDS, rows)
    return rows


def load_options(ads: Session, version: str, start: date, end: date, dimensions: dict[str, dict]) -> dict:
    try:
        rows = ads.execute(text(f"""
            SELECT DISTINCT `brand`, `channel`, `product_type`
            FROM `{TABLE}`
            WHERE `data_version` = :data_version AND `sales_date` BETWEEN :start_date AND :end_date
        """), {"data_version": version, "start_date": start, "end_date": end}).mappings().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, "销售毛利分析数据尚未就绪，请重新发布 sales_profit 数据集") from exc
    channels = sorted({str(row["channel"] or "未归类") for row in rows})
    return {
        "owners": sorted({dimensions.get(name, {}).get("owner", "未分配") for name in channels}),
        "brands": sorted({str(row["brand"]) for row in rows if row["brand"]}),
        "channels": channels,
        "product_types": sorted({str(row["product_type"]) for row in rows if row["product_type"]}),
    }


def prepare_rows(raw: list[dict], dimensions: dict[str, dict], params: AnalysisParams) -> list[dict]:
    rows = []
    for source in raw:
        item = dict(source)
        channel = str(item.get("channel") or "未归类").strip()
        dimension = dimensions.get(channel, {})
        customer_code = str(item.get("customer_code") or "").strip()
        item.update({
            "channel": channel,
            "owner": dimension.get("owner", "未分配"),
            "channel_type": dimension.get("channel_type", "线上" if is_online_sales_channel(None, None, channel) else "线下"),
            "customer_code": customer_code,
            "customer_name": str(item.get("customer_name") or (f"客户 {customer_code}" if customer_code else "未识别客户")),
            "product_code": str(item.get("product_code") or "").strip(),
            "product_name": str(item.get("product_name") or "未命名货品"),
            "brand": str(item.get("brand") or "未识别品牌"),
            "product_type": str(item.get("product_type") or "未分类"),
        })
        for field in NUMERIC_INPUTS:
            # Source amounts have two decimals; SQLite SUM can introduce binary tails.
            scale = Decimal("0.0001") if "quantity" in field else Decimal("0.01")
            item[field] = decimal(item.get(field)).quantize(scale, rounding=ROUND_HALF_UP)
        if params.channel_type != "all" and item["channel_type"] != {"online": "线上", "offline": "线下"}[params.channel_type]:
            continue
        rows.append(item)
    return rows


def reference_key(row: dict) -> tuple:
    return row["product_code"], row["brand"], row["product_type"], row["channel_type"]


def eligible(row: dict) -> bool:
    return bool(row["product_code"] and row["product_code"] != "-" and row["sale_quantity"] > 0)


def reference_totals(rows: list[dict], mode: str) -> dict[tuple, tuple[Decimal, Decimal]]:
    totals = {}
    for row in rows:
        if not eligible(row) or not row["customer_code"]:
            continue
        key = reference_key(row)
        if mode in {"peers", "previous"}:
            key += (row["owner"],)
        if mode == "previous":
            key += (row["customer_code"],)
        amount, quantity = totals.get(key, (ZERO, ZERO))
        totals[key] = amount + row["sale_amount"], quantity + row["sale_quantity"]
    return totals


def enrich_rows(rows: list[dict], prices: dict, previous_rows: list[dict], params: AnalysisParams) -> list[dict]:
    references = reference_totals(previous_rows if params.benchmark == "previous" else rows, params.benchmark)
    # Peer references exclude the entire client, including its other channels.
    client_totals = reference_totals(rows, "previous") if params.benchmark == "peers" else {}
    enriched = []
    for original in rows:
        row = dict(original)
        if params.owner.strip() and row["owner"] != params.owner.strip():
            continue
        customer_keyword = params.customer_keyword.strip().casefold()
        if customer_keyword and not any(customer_keyword in row[field].casefold() for field in ("customer_code", "customer_name")):
            continue
        revision = prices.get(row["product_code"])
        cost = decimal(getattr(revision, "price", revision)) if revision is not None else None
        cost = cost if cost is not None and cost > 0 and row["product_code"] and row["product_code"] != "-" else None
        row["core_cost"] = cost
        row["estimated_cost"] = row["sale_quantity"] * cost if cost is not None and row["sale_quantity"] > 0 else None
        row["estimated_profit"] = row["sale_amount"] - row["estimated_cost"] if row["estimated_cost"] is not None else None
        row["margin_rate"] = percent(row["estimated_profit"], row["sale_amount"]) if row["estimated_profit"] is not None else None
        row["avg_price"] = row["sale_amount"] / row["sale_quantity"] if eligible(row) else None
        row["reference_price"] = None
        row["reference_quantity"] = None
        row["price_delta"] = None
        row["price_delta_rate"] = None
        row["price_effect_amount"] = None
        row["cost_coverage_rate"] = Decimal("100") if cost is not None else ZERO
        row["below_cost"] = (
            cost is not None and row["avg_price"] is not None and row["avg_price"] < cost
        )
        row["loss_sales_amount"] = row["sale_amount"] if row["below_cost"] else ZERO
        if eligible(row) and row["customer_code"]:
            key = reference_key(row)
            if params.benchmark in {"peers", "previous"}:
                key += (row["owner"],)
            if params.benchmark == "previous":
                key += (row["customer_code"],)
            amount, quantity = references.get(key, (ZERO, ZERO))
            if params.benchmark == "peers":
                client_amount, client_quantity = client_totals.get(key + (row["customer_code"],), (ZERO, ZERO))
                amount -= client_amount
                quantity -= client_quantity
            if quantity > 0:
                row["reference_price"] = amount / quantity
                row["reference_quantity"] = quantity
                row["price_delta"] = row["avg_price"] - row["reference_price"]
                row["price_delta_rate"] = percent(row["price_delta"], row["reference_price"])
                row["price_effect_amount"] = row["price_delta"] * row["sale_quantity"]
        if params.cost_status == "priced" and cost is None:
            continue
        if params.cost_status == "missing" and cost is not None:
            continue
        if params.cost_status == "loss" and not row["below_cost"]:
            continue
        if params.price_direction == "unmatched" and row["reference_price"] is not None:
            continue
        if params.price_direction in {"above", "below"} and (
            row["price_delta"] is None or
            (params.price_direction == "above" and row["price_delta"] <= 0) or
            (params.price_direction == "below" and row["price_delta"] >= 0)
        ):
            continue
        enriched.append(row)
    return enriched


def summarize(rows: list[dict]) -> dict:
    total = {field: sum((row[field] for row in rows), ZERO) for field in NUMERIC_INPUTS}
    priced = [row for row in rows if row["core_cost"] is not None]
    profit_rows = [row for row in priced if row["estimated_cost"] is not None]
    priced_amount = sum((row["sale_amount"] for row in profit_rows), ZERO)
    estimated_cost = sum((row["estimated_cost"] for row in profit_rows), ZERO)
    estimated_profit = priced_amount - estimated_cost if profit_rows else None
    total.update({
        "priced_amount": priced_amount,
        "missing_cost_amount": sum((row["sale_amount"] for row in rows if row["core_cost"] is None), ZERO),
        "estimated_cost": estimated_cost if profit_rows else None,
        "estimated_profit": estimated_profit,
        "margin_rate": percent(estimated_profit, priced_amount) if profit_rows else None,
        "cost_coverage_rate": percent(sum((row["sale_amount"] for row in priced), ZERO), total["sale_amount"]),
        "identified_customer_rate": percent(sum((row["sale_amount"] for row in rows if row["customer_code"]), ZERO), total["sale_amount"]),
        "loss_sales_amount": sum((row["loss_sales_amount"] for row in rows), ZERO),
        "compared_rows": sum(row["reference_price"] is not None for row in rows),
    })
    return {key: number(value, 4 if "quantity" in key else 2) if isinstance(value, Decimal) else value for key, value in total.items()}


def breakdown(rows: list[dict], group_by: str) -> list[dict]:
    field = {"customer": "customer_code", "product": "product_code"}.get(group_by, group_by)
    groups = {}
    for row in rows:
        groups.setdefault(row[field], []).append(row)
    result = []
    for key, items in groups.items():
        label = items[0][{"customer": "customer_name", "product": "product_name"}.get(group_by, field)]
        metrics = summarize(items)
        result.append({
            "key": key, "label": label, "quantity": metrics["quantity"],
            "paid_amount": metrics["paid_amount"], "sale_quantity": metrics["sale_quantity"],
            "sale_amount": metrics["sale_amount"], "estimated_profit": metrics["estimated_profit"],
            "margin_rate": metrics["margin_rate"], "cost_coverage_rate": metrics["cost_coverage_rate"],
        })
    return sorted(result, key=lambda row: (
        row["estimated_profit"] is None, -(row["estimated_profit"] or 0), -row["paid_amount"], row["key"],
    ))


def serialize_row(row: dict) -> dict:
    return {
        key: number(value, 4 if "quantity" in key else 2) if isinstance(value, Decimal) else value
        for key, value in row.items() if key != "loss_sales_amount"
    }


def sort_rows(rows: list[dict], params: AnalysisParams) -> list[dict]:
    field = params.sort_by or ("price_effect_amount" if params.view == "prices" else "estimated_profit")
    if field not in SORT_FIELDS:
        raise HTTPException(422, "不支持该排序字段")
    stable = sorted(rows, key=lambda row: (
        row["owner"], row["customer_code"], row["product_code"], row["channel"], row["brand"], row["product_type"],
    ))
    populated = [row for row in stable if row.get(field) is not None]
    missing = [row for row in stable if row.get(field) is None]
    populated.sort(key=lambda row: row[field], reverse=params.sort_order == "desc")
    return populated + missing


def analyze(ads: Session, ods: Session, prices: dict, params: AnalysisParams, export: bool = False) -> dict:
    batch = latest_batch(ads)
    start, end, previous_start, previous_end = resolve_period(params, batch)
    dimensions = load_channel_dimensions(ods)
    options = load_options(ads, batch.data_version, start, end, dimensions)
    owner_channels = tuple(
        channel for channel in options["channels"]
        if dimensions.get(channel, {}).get("owner", "未分配") == params.owner.strip()
    ) if params.owner.strip() else None
    raw = load_aggregates(ads, params, batch.data_version, start, end, owner_channels)
    rows = prepare_rows(raw, dimensions, params)
    previous_rows = prepare_rows(load_aggregates(
        ads, params, batch.data_version, previous_start, previous_end, owner_channels,
    ), dimensions, params) if params.benchmark == "previous" else []
    enriched = enrich_rows(rows, prices, previous_rows, params)
    grouped = breakdown(enriched, params.group_by)
    sorted_rows = sort_rows(enriched, params)
    selected_rows = sorted_rows if export else sorted_rows[(params.page - 1) * params.page_size:params.page * params.page_size]
    metadata = batch.reconciliation or {}
    updated_at = metadata.get("source_max_updated_at") or batch.published_at or batch.finished_at
    return {
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "as_of": date_value(metadata.get("max_sales_date") or batch.source_end_date).isoformat(),
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else updated_at,
        "cost_as_of": date.today().isoformat(), "source_start_date": batch.source_start_date.isoformat(),
        "source_end_date": batch.source_end_date.isoformat(),
        "previous_start_date": previous_start.isoformat(), "previous_end_date": previous_end.isoformat(),
        "loss_basis": "customer_sku_average", "owner_basis": "current_channel_owner", "cost_basis": "current_core_cost",
        "options": options,
        "summary": summarize(enriched), "breakdown": grouped[:100], "breakdown_total": len(grouped),
        "rows": [serialize_row(row) for row in selected_rows],
        "pagination": {"page": params.page, "page_size": params.page_size, "total": len(enriched)},
    }
