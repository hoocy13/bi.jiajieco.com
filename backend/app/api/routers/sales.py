import logging
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.ads import AdsSessionLocal
from app.db.ods import get_ods_db
from app.models.user import User
from app.schemas.common import ok
from app.services.sales_sources import (
    ACTIVE_SALES_ORDER_SQL,
    BRAND_EXPRESSION_SQL,
    POSITIVE_SALES_ORDER_COUNT_SQL,
    SALES_DETAIL_TABLE_SQL,
    SALES_ORDER_TABLE_SQL,
    is_online_sales_channel,
)
from app.services.sales_ads import (
    AdsDataUnavailable,
    compare_sales_overviews,
    latest_ready_sales_batch,
    load_sales_brand_analysis_from_ads,
    load_sales_brand_channel_from_ads,
    load_sales_channel_customer_from_ads,
    load_sales_customer_analysis_from_ads,
    load_sales_channel_analysis_from_ads,
    load_sales_detail_from_ads,
    load_sales_overview_from_ads,
    load_sales_product_rank_from_ads,
)


router = APIRouter(prefix="/sales", tags=["sales"])
logger = logging.getLogger("uvicorn.error")

RANGE_OPTIONS = {
    "last_30": "近30天",
    "this_month": "本月",
    "this_year": "本年",
}

SALES_CACHE_TTL_SECONDS = 300
SALES_CACHE_MAX_ITEMS = 256
_sales_cache: dict[tuple, tuple[float, dict]] = {}
_sales_cache_lock = Lock()


def _get_sales_overview_ods_db():
    if settings.BI_QUERY_SOURCE == "ads":
        yield None
        return
    yield from get_ods_db()


def _cache_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        return tuple(sorted(_cache_value(item) for item in value))
    return value


def _sales_cache_key(endpoint: str, **params: object) -> tuple:
    return (endpoint, tuple(sorted((key, _cache_value(value)) for key, value in params.items())))


def _get_sales_cache(key: tuple) -> dict | None:
    now = monotonic()
    with _sales_cache_lock:
        cached = _sales_cache.get(key)
        if cached is None:
            return None

        expires_at, data = cached
        if expires_at <= now:
            _sales_cache.pop(key, None)
            return None

        return deepcopy(data)


def _set_sales_cache(key: tuple, data: dict) -> None:
    now = monotonic()
    with _sales_cache_lock:
        if len(_sales_cache) >= SALES_CACHE_MAX_ITEMS:
            expired_keys = [cache_key for cache_key, (expires_at, _) in _sales_cache.items() if expires_at <= now]
            for cache_key in expired_keys:
                _sales_cache.pop(cache_key, None)
            if len(_sales_cache) >= SALES_CACHE_MAX_ITEMS:
                oldest_key = min(_sales_cache, key=lambda cache_key: _sales_cache[cache_key][0])
                _sales_cache.pop(oldest_key, None)

        _sales_cache[key] = (now + SALES_CACHE_TTL_SECONDS, deepcopy(data))


def _cached_ok(key: tuple, data: dict) -> dict:
    _set_sales_cache(key, data)
    return ok(data)


def _normal_request_context() -> bool:
    return False


def _query_result(key: tuple, data: dict, export_mode: bool) -> dict:
    return ok(data) if export_mode else _cached_ok(key, data)


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return 0
    return float(value)


def _int(value: object) -> int:
    if value is None:
        return 0
    return int(value)


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _range_bounds(
    range_key: str,
    as_of: date,
    custom_start_date: date | None,
    custom_end_date: date | None,
) -> tuple[date, date, str, str]:
    if custom_start_date or custom_end_date:
        if not custom_start_date or not custom_end_date:
            raise HTTPException(status_code=400, detail="start_date and end_date must be used together")
        if custom_start_date > custom_end_date:
            raise HTTPException(status_code=400, detail="start_date cannot be later than end_date")
        return custom_start_date, custom_end_date, "自定义", "custom"

    if range_key not in RANGE_OPTIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported sales range: {range_key}")

    if range_key == "last_30":
        return as_of - timedelta(days=29), as_of, RANGE_OPTIONS[range_key], range_key

    if range_key == "this_year":
        return date(as_of.year, 1, 1), as_of, RANGE_OPTIONS[range_key], range_key

    return date(as_of.year, as_of.month, 1), as_of, RANGE_OPTIONS[range_key], range_key


def _empty_sales_payload(range_key: str, start_date: date | None, end_date: date | None) -> dict:
    return {
        "as_of": None,
        "period": RANGE_OPTIONS.get(range_key, "近30天"),
        "range": "custom" if start_date or end_date else range_key,
        "start_date": None,
        "end_date": None,
    }


def _resolve_sales_period(
    db: Session,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[dict, dict] | tuple[None, dict]:
    max_date = db.execute(
        text(f"SELECT MAX(`下单时间`) FROM {SALES_ORDER_TABLE_SQL} WHERE {ACTIVE_SALES_ORDER_SQL}")
    ).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return None, _empty_sales_payload(range_key, start_date, end_date)

    resolved_start, resolved_end, period, applied_range = _range_bounds(range_key, as_of, start_date, end_date)
    meta = {
        "as_of": as_of.isoformat(),
        "period": period,
        "range": applied_range,
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
    }
    params = {"start_date": resolved_start, "end_date": resolved_end}
    return params, meta


def _resolve_detail_sales_period(
    db: Session,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
) -> tuple[dict, dict] | tuple[None, dict]:
    max_date = db.execute(
        text("SELECT MAX(`下单时间`) FROM `dwd`.`销售单明细账_品牌补全`")
    ).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return None, _empty_sales_payload(range_key, start_date, end_date)

    resolved_start, resolved_end, period, applied_range = _range_bounds(range_key, as_of, start_date, end_date)
    meta = {
        "as_of": as_of.isoformat(),
        "period": period,
        "range": applied_range,
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
    }
    params = {"start_date": resolved_start, "end_date": resolved_end}
    return params, meta


def _sales_query_summary(db: Session, params: dict) -> dict:
    row = db.execute(
        text(
            f"""
            SELECT
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            """
        ),
        params,
    ).mappings().one()
    return {
        "paid_amount": _number(row["paid_amount"]),
        "orders": _int(row["orders"]),
        "quantity": _int(row["quantity"]),
    }


def _load_ads_overview(
    range_key: str,
    start_date: date | None,
    end_date: date | None,
    meta: dict | None = None,
) -> dict:
    if AdsSessionLocal is None:
        raise AdsDataUnavailable("ADS_DATABASE_URL is not configured")

    with AdsSessionLocal() as ads_db:
        batch = latest_ready_sales_batch(ads_db)
        if meta is None:
            as_of = batch.source_end_date
            resolved_start, resolved_end, period, applied_range = _range_bounds(
                range_key,
                as_of,
                start_date,
                end_date,
            )
            meta = {
                "as_of": as_of.isoformat(),
                "period": period,
                "range": applied_range,
                "start_date": resolved_start.isoformat(),
                "end_date": resolved_end.isoformat(),
            }
        return load_sales_overview_from_ads(ads_db, batch, meta)


def _validate_ads_overview(ods_data: dict, range_key: str, start_date: date | None, end_date: date | None) -> str:
    try:
        ads_data = _load_ads_overview(
            range_key,
            start_date,
            end_date,
            meta={
                key: ods_data[key]
                for key in ("as_of", "period", "range", "start_date", "end_date")
            },
        )
        differences = compare_sales_overviews(ods_data, ads_data)
        if differences:
            paths = ",".join(difference.path for difference in differences[:20])
            logger.warning(
                "sales_overview_dual status=mismatch difference_count=%s paths=%s",
                len(differences),
                paths,
            )
            return "mismatch"

        logger.info("sales_overview_dual status=matched")
        return "matched"
    except AdsDataUnavailable:
        logger.warning("sales_overview_dual status=unavailable")
        return "unavailable"
    except Exception as exc:
        logger.warning("sales_overview_dual status=error error_type=%s", type(exc).__name__)
        return "error"


def _load_ads_product_rank(
    range_key: str,
    start_date: date | None,
    end_date: date | None,
    limit: int,
    keyword: str | None,
) -> dict:
    if AdsSessionLocal is None:
        raise AdsDataUnavailable("ADS_DATABASE_URL is not configured")

    with AdsSessionLocal() as ads_db:
        batch = latest_ready_sales_batch(ads_db)
        as_of = batch.source_end_date
        resolved_start, resolved_end, period, applied_range = _range_bounds(
            range_key,
            as_of,
            start_date,
            end_date,
        )
        meta = {
            "as_of": as_of.isoformat(),
            "period": period,
            "range": applied_range,
            "start_date": resolved_start.isoformat(),
            "end_date": resolved_end.isoformat(),
        }
        return load_sales_product_rank_from_ads(
            ads_db,
            batch,
            meta,
            limit=limit,
            keyword=keyword,
        )


def _load_ads_brand_analysis(
    range_key: str,
    start_date: date | None,
    end_date: date | None,
    limit: int,
    product_types: list[str],
) -> dict:
    if AdsSessionLocal is None:
        raise AdsDataUnavailable("ADS_DATABASE_URL is not configured")

    with AdsSessionLocal() as ads_db:
        batch = latest_ready_sales_batch(ads_db)
        as_of = batch.source_end_date
        resolved_start, resolved_end, period, applied_range = _range_bounds(
            range_key,
            as_of,
            start_date,
            end_date,
        )
        meta = {
            "as_of": as_of.isoformat(),
            "period": period,
            "range": applied_range,
            "start_date": resolved_start.isoformat(),
            "end_date": resolved_end.isoformat(),
        }
        return load_sales_brand_analysis_from_ads(
            ads_db,
            batch,
            meta,
            limit=limit,
            product_types=product_types,
        )


def _load_ads_channel_analysis(
    db: Session,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
    keyword: str | None,
    channel_type: str | None,
    platform: str | None,
    authorized: str | None,
) -> dict:
    if AdsSessionLocal is None:
        raise AdsDataUnavailable("ADS_DATABASE_URL is not configured")

    params: dict[str, object] = {}
    filters: list[str] = []
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append(
            "(`渠道名称` LIKE :keyword OR `渠道编号` LIKE :keyword "
            "OR `负责人` LIKE :keyword OR `线上平台` LIKE :keyword)"
        )
    if channel_type:
        params["channel_type"] = channel_type
        filters.append("COALESCE(NULLIF(`渠道类型`, ''), '未分类') = :channel_type")
    if platform:
        params["platform"] = platform
        filters.append("COALESCE(NULLIF(`线上平台`, ''), '未设置') = :platform")
    if authorized in {"0", "1"}:
        params["authorized"] = authorized
        filters.append("CAST(COALESCE(`是否授权`, 0) AS CHAR) = :authorized")
    channel_where = f"WHERE {' AND '.join(filters)}" if filters else ""

    dimension_rows = [
        dict(row)
        for row in db.execute(
            text(
                f"""
                SELECT
                  `渠道编号` AS channel_code,
                  `渠道名称` AS channel_name,
                  COALESCE(NULLIF(`分类`, ''), '未分类') AS category,
                  COALESCE(NULLIF(`渠道类型`, ''), '未分类') AS channel_type,
                  COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform,
                  COALESCE(NULLIF(`负责人`, ''), '-') AS owner,
                  COALESCE(`是否授权`, 0) AS authorized
                FROM `渠道列表`
                {channel_where}
                ORDER BY `渠道编号`
                """
            ),
            params,
        ).mappings().all()
    ]
    filter_option_rows = [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT
                  COALESCE(NULLIF(`渠道类型`, ''), '未分类') AS channel_type,
                  COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform,
                  `渠道名称` AS channel_name
                FROM `渠道列表`
                """
            )
        ).mappings().all()
    ]
    include_unmatched = (
        not keyword
        and (not channel_type or channel_type == "未分类")
        and (not platform or platform == "未设置")
        and authorized != "1"
    )

    with AdsSessionLocal() as ads_db:
        batch = latest_ready_sales_batch(ads_db)
        as_of = batch.source_end_date
        resolved_start, resolved_end, period, applied_range = _range_bounds(
            range_key,
            as_of,
            start_date,
            end_date,
        )
        meta = {
            "as_of": as_of.isoformat(),
            "period": period,
            "range": applied_range,
            "start_date": resolved_start.isoformat(),
            "end_date": resolved_end.isoformat(),
        }
        return load_sales_channel_analysis_from_ads(
            ads_db,
            batch,
            meta,
            dimension_rows=dimension_rows,
            filter_option_rows=filter_option_rows,
            include_unmatched=include_unmatched,
        )


def _ads_period_meta(
    batch,
    range_key: str,
    start_date: date | None,
    end_date: date | None,
) -> dict:
    as_of = batch.source_end_date
    resolved_start, resolved_end, period, applied_range = _range_bounds(
        range_key, as_of, start_date, end_date
    )
    return {
        "as_of": as_of.isoformat(),
        "period": period,
        "range": applied_range,
        "start_date": resolved_start.isoformat(),
        "end_date": resolved_end.isoformat(),
    }


@router.get("/overview")
def sales_overview(
    response: Response,
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(_get_sales_overview_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "overview",
        range=range,
        start_date=start_date,
        end_date=end_date,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        if query_mode == "dual":
            response.headers["X-BI-Dual-Status"] = "cached"
        return ok(cached)

    if query_mode == "ads":
        try:
            data = _load_ads_overview(range, start_date, end_date)
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("sales_overview_ads status=error error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="ADS database is temporarily unavailable") from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    if db is None:
        raise HTTPException(status_code=503, detail="ODS database is not configured")
    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_sales_period(db, range, start_date, end_date)
    if params is None:
        data = {
            **meta,
            "metrics": {
                "paid_amount": 0,
                "orders": 0,
                "quantity": 0,
                "avg_order_amount": 0,
            },
            "trend": [],
            "channels": [],
        }
        return _cached_ok(cache_key, data)

    metrics = _sales_query_summary(db, params)

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS day,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY DATE(`下单时间`)
            ORDER BY day
            """
        ),
        params,
    ).mappings().all()

    channel_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY paid_amount DESC
            LIMIT 10
            """
        ),
        params,
    ).mappings().all()

    orders = metrics["orders"]
    paid_amount = metrics["paid_amount"]
    quantity = metrics["quantity"]
    avg_order_amount = paid_amount / orders if orders else 0

    data = {
        **meta,
        "metrics": {
            "paid_amount": paid_amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": avg_order_amount,
        },
        "trend": [
            {
                "date": row["day"].isoformat(),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
            }
            for row in trend_rows
        ],
        "channels": [
            {
                "channel": row["channel"],
                "orders": orders_count,
                "paid_amount": channel_paid_amount,
                "quantity": quantity_count,
                "share": channel_paid_amount / paid_amount * 100 if paid_amount else 0,
                "avg_order_amount": channel_paid_amount / orders_count if orders_count else 0,
            }
            for row in channel_rows
            for orders_count in [_int(row["orders"])]
            for channel_paid_amount in [_number(row["paid_amount"])]
            for quantity_count in [_int(row["quantity"])]
        ],
    }
    if query_mode == "dual":
        response.headers["X-BI-Dual-Status"] = _validate_ads_overview(
            data,
            range,
            start_date,
            end_date,
        )
    return _cached_ok(cache_key, data)


@router.get("/detail")
def sales_detail(
    response: Response,
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    keyword: str | None = Query(None),
    channel: str | None = Query(None),
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(_get_sales_overview_ods_db),
    _export: bool = Depends(_normal_request_context),
) -> dict:
    export_mode = _export is True
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "detail",
        range=range,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
        keyword=keyword,
        channel=channel,
        status=status,
        query_mode=query_mode,
    )
    cached = None if export_mode else _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        if AdsSessionLocal is None:
            raise HTTPException(status_code=503, detail="ADS database is not configured")
        try:
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_sales_batch(ads_db)
                data = load_sales_detail_from_ads(
                    ads_db,
                    batch,
                    _ads_period_meta(batch, range, start_date, end_date),
                    page,
                    page_size,
                    keyword,
                    channel,
                    status,
                )
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _query_result(cache_key, data, export_mode)

    if db is None:
        raise HTTPException(status_code=503, detail="ODS database is not configured")
    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_sales_period(db, range, start_date, end_date)
    if params is None:
        data = {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": [], "total": 0}
        return _query_result(cache_key, data, export_mode)

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
        ACTIVE_SALES_ORDER_SQL,
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("(`订单编号` LIKE :keyword OR `货品摘要` LIKE :keyword)")
    if channel:
        params["channel"] = channel
        filters.append("COALESCE(NULLIF(`销售渠道`, ''), '未归类') = :channel")
    if status:
        params["status"] = status
        filters.append("COALESCE(NULLIF(`订单状态`, ''), '未知') = :status")

    where_sql = " AND ".join(filters)
    summary_row = db.execute(
        text(
            f"""
            SELECT
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount,
              SUM(COALESCE(`货品数量`, 0)) AS quantity
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    total = db.execute(
        text(f"SELECT COUNT(*) FROM {SALES_ORDER_TABLE_SQL} WHERE {where_sql}"),
        params,
    ).scalar()

    row_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS order_date,
              `订单编号` AS order_no,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              COALESCE(NULLIF(`订单状态`, ''), '未知') AS status,
              COALESCE(NULLIF(`结算状态`, ''), '未知') AS settlement_status,
              COALESCE(NULLIF(`货品摘要`, ''), '未命名商品') AS product,
              COALESCE(`货品数量`, 0) AS quantity,
              COALESCE(`应收合计`, 0) AS receivable_amount,
              COALESCE(`实付金额`, 0) AS paid_amount,
              COALESCE(NULLIF(`市`, ''), '-') AS city
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE {where_sql}
            ORDER BY `下单时间` DESC, `订单编号` DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": {
            "paid_amount": _number(summary_row["paid_amount"]),
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "date": row["order_date"].isoformat() if row["order_date"] else None,
                "order_no": row["order_no"],
                "channel": row["channel"],
                "status": row["status"],
                "settlement_status": row["settlement_status"],
                "product": row["product"],
                "quantity": _int(row["quantity"]),
                "receivable_amount": _number(row["receivable_amount"]),
                "paid_amount": _number(row["paid_amount"]),
                "city": row["city"],
            }
            for row in rows
        ],
        "total": _int(total),
        "page": page,
        "page_size": page_size,
    }
    return _query_result(cache_key, data, export_mode)


@router.get("/product-rank")
def sales_product_rank(
    response: Response,
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(30, ge=10, le=100),
    keyword: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "product-rank-v3",
        range=range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        keyword=keyword,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        try:
            data = _load_ads_product_rank(
                range,
                start_date,
                end_date,
                limit,
                keyword,
            )
            if keyword:
                exact_orders = db.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT `订单编号`)
                        FROM `dwd`.`销售单明细账_品牌补全`
                        WHERE `下单时间` >= :start_date
                          AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
                          AND `货品名称` LIKE :keyword
                        """
                    ),
                    {
                        "start_date": date.fromisoformat(data["start_date"]),
                        "end_date": date.fromisoformat(data["end_date"]),
                        "keyword": f"%{keyword.strip()}%",
                    },
                ).scalar()
                data["rank_summary"]["orders"] = _int(exact_orders)
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("sales_product_rank_ads status=error error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="ADS database is temporarily unavailable") from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(cache_key, {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": []})

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("`货品名称` LIKE :keyword")

    where_sql = " AND ".join(filters)
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    rank_paid_amount = _number(summary_row["paid_amount"])
    summary = _sales_query_summary(db, params)
    row_params = {**params, "limit": limit}
    rank_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY paid_amount DESC
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()
    quantity_rank_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {where_sql}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY quantity DESC, paid_amount DESC
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": summary,
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": amount / rank_paid_amount * 100 if rank_paid_amount else 0,
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
        "quantity_rows": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": quantity / _int(summary_row["quantity"]) * 100 if _int(summary_row["quantity"]) else 0,
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(quantity_rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/brand-analysis")
def sales_brand_analysis(
    response: Response,
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    limit: int = Query(30, ge=10, le=100),
    keyword: str | None = Query(None),
    product_type: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    selected_product_types = list(
        dict.fromkeys(item.strip() for item in product_type or [] if item.strip() in {"正装", "小样"})
    )
    cache_key = _sales_cache_key(
        "brand-analysis-v3",
        range=range,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        keyword=keyword,
        product_type=selected_product_types,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = (
            "ads" if query_mode == "ads" and not keyword else "ods"
        )
        return ok(cached)

    if query_mode == "ads" and not keyword:
        try:
            data = _load_ads_brand_analysis(
                range,
                start_date,
                end_date,
                limit,
                selected_product_types,
            )
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("sales_brand_analysis_ads status=error error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="ADS database is temporarily unavailable") from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(cache_key, {**meta, "summary": {"paid_amount": 0, "orders": 0, "quantity": 0}, "rows": []})

    filters = [
        "`下单时间` >= :start_date",
        "`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)",
    ]
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("(`品牌` LIKE :keyword OR `货品名称` LIKE :keyword)")
    if selected_product_types:
        product_type_params = []
        for index, item in enumerate(selected_product_types):
            param_name = f"product_type_{index}"
            params[param_name] = item
            product_type_params.append(f":{param_name}")
        filters.append(
            f"COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类') IN ({', '.join(product_type_params)})"
        )

    where_sql = " AND ".join(filters)
    brand_expr = BRAND_EXPRESSION_SQL
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    rank_paid_amount = _number(summary_row["paid_amount"])
    summary = (
        {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        }
        if selected_product_types
        else _sales_query_summary(db, params)
    )
    row_params = {**params, "limit": limit}
    rank_rows = db.execute(
        text(
            f"""
            SELECT
              {brand_expr} AS brand,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              COUNT(DISTINCT COALESCE(NULLIF(`货品名称`, ''), '未命名商品')) AS product_count,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {where_sql}
            GROUP BY {brand_expr}
            ORDER BY paid_amount DESC, brand
            LIMIT :limit
            """
        ),
        row_params,
    ).mappings().all()

    data = {
        **meta,
        "summary": summary,
        "rank_summary": {
            "paid_amount": rank_paid_amount,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
        },
        "rows": [
            {
                "rank": index + 1,
                "brand": row["brand"],
                "orders": orders,
                "quantity": quantity,
                "paid_amount": amount,
                "share": amount / rank_paid_amount * 100 if rank_paid_amount else 0,
                "product_count": _int(row["product_count"]),
                "avg_unit_price": amount / quantity if quantity else 0,
            }
            for index, row in enumerate(rank_rows)
            for orders in [_int(row["orders"])]
            for quantity in [_int(row["quantity"])]
            for amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/channel-analysis")
def sales_channel_analysis(
    response: Response,
    range: str = Query("this_year"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    keyword: str | None = Query(None),
    channel_type: str | None = Query(None),
    platform: str | None = Query(None),
    authorized: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "channel-analysis-v7",
        range=range,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
        channel_type=channel_type,
        platform=platform,
        authorized=authorized,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        try:
            data = _load_ads_channel_analysis(
                db,
                range,
                start_date,
                end_date,
                keyword,
                channel_type,
                platform,
                authorized,
            )
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning("sales_channel_analysis_ads status=error error_type=%s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="ADS database is temporarily unavailable") from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "summary": {"paid_amount": 0, "orders": 0, "quantity": 0},
                "channel_summary": {
                    "total_channels": 0,
                    "active_channels": 0,
                    "authorized_channels": 0,
                    "unmatched_sales_channels": 0,
                },
                "trend": [],
                "type_summary": [],
                "platform_summary": [],
                "rows": [],
                "unmatched_channels": [],
                "filter_options": {"channel_types": [], "platforms": []},
            },
        )

    filters = []
    sales_dimension_filters = []
    if keyword:
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append(
            "(`渠道名称` LIKE :keyword OR `渠道编号` LIKE :keyword OR `负责人` LIKE :keyword OR `线上平台` LIKE :keyword)"
        )
        sales_dimension_filters.append(
            "(c.`渠道名称` LIKE :keyword OR c.`渠道编号` LIKE :keyword OR c.`负责人` LIKE :keyword OR c.`线上平台` LIKE :keyword)"
        )
    if channel_type:
        params["channel_type"] = channel_type
        filters.append("COALESCE(NULLIF(`渠道类型`, ''), '未分类') = :channel_type")
        sales_dimension_filters.append("COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') = :channel_type")
    if platform:
        params["platform"] = platform
        filters.append("COALESCE(NULLIF(`线上平台`, ''), '未设置') = :platform")
        sales_dimension_filters.append("COALESCE(NULLIF(c.`线上平台`, ''), '未设置') = :platform")
    if authorized in {"0", "1"}:
        params["authorized"] = authorized
        filters.append("CAST(COALESCE(`是否授权`, 0) AS CHAR) = :authorized")
        sales_dimension_filters.append("CAST(COALESCE(c.`是否授权`, 0) AS CHAR) = :authorized")

    channel_where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sales_dimension_where = (
        f"AND {' AND '.join(sales_dimension_filters)}" if sales_dimension_filters else ""
    )
    monthly_channel_rows = db.execute(
        text(
            f"""
            SELECT
              DATE_FORMAT(s.`下单时间`, '%Y-%m-01') AS month,
              COALESCE(NULLIF(s.`销售渠道`, ''), '未归类') AS channel,
              COUNT(DISTINCT s.`订单编号`) AS orders,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS paid_amount,
              SUM(COALESCE(s.`数量`, 0)) AS quantity
            FROM `dwd`.`销售单明细账_品牌补全` s
            LEFT JOIN `渠道列表` c
              ON c.`渠道名称` = COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            WHERE s.`下单时间` >= :start_date
              AND s.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              {sales_dimension_where}
            GROUP BY DATE_FORMAT(s.`下单时间`, '%Y-%m-01'), COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            ORDER BY month, channel
            """
        ),
        params,
    ).mappings().all()
    trend_by_month: dict[str, dict] = {}
    facts_by_channel: dict[str, dict] = {}
    for row in monthly_channel_rows:
        month = str(row["month"])
        channel = row["channel"]
        month_item = trend_by_month.setdefault(
            month, {"month": month, "orders": 0, "paid_amount": 0.0, "quantity": 0}
        )
        channel_item = facts_by_channel.setdefault(
            channel, {"channel": channel, "orders": 0, "paid_amount": 0.0, "quantity": 0}
        )
        for item in (month_item, channel_item):
            item["orders"] += _int(row["orders"])
            item["paid_amount"] += _number(row["paid_amount"])
            item["quantity"] += _int(row["quantity"])
    trend = list(trend_by_month.values())
    summary = {
        "orders": sum(row["orders"] for row in trend),
        "paid_amount": sum(row["paid_amount"] for row in trend),
        "quantity": sum(row["quantity"] for row in trend),
    }
    dimension_rows = db.execute(
        text(
            f"""
            SELECT
              c.`渠道编号` AS channel_code,
              c.`渠道名称` AS channel_name,
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS category,
              COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COALESCE(NULLIF(c.`负责人`, ''), '-') AS owner,
              COALESCE(c.`是否授权`, 0) AS authorized
            FROM `渠道列表` c
            {channel_where}
            ORDER BY c.`渠道编号`
            """
        ),
        params,
    ).mappings().all()

    total_paid_amount = summary["paid_amount"]
    channel_rows = [
        {
            "channel_code": row["channel_code"],
            "channel_name": row["channel_name"],
            "category": row["category"],
            "channel_type": row["channel_type"],
            "platform": row["platform"],
            "owner": row["owner"],
            "authorized": str(row["authorized"]) == "1",
            "orders": orders,
            "paid_amount": paid_amount,
            "quantity": quantity,
            "share": paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
            "avg_order_amount": paid_amount / orders if orders else 0,
            "is_online": is_online_sales_channel(
                row["category"], row["platform"], row["channel_name"]
            ),
            "matched": True,
        }
        for row in dimension_rows
        for fact in [facts_by_channel.get(row["channel_name"], {})]
        for orders in [_int(fact.get("orders"))]
        for paid_amount in [_number(fact.get("paid_amount"))]
        for quantity in [_int(fact.get("quantity"))]
    ]

    filter_option_rows = db.execute(
        text(
            """
            SELECT
              COALESCE(NULLIF(`渠道类型`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform,
              `渠道名称` AS channel_name
            FROM `渠道列表`
            """
        )
    ).mappings().all()
    channel_types = sorted({row["channel_type"] for row in filter_option_rows})
    platforms = sorted({row["platform"] for row in filter_option_rows if row["platform"] != "未设置"})
    all_channel_names = {row["channel_name"] for row in filter_option_rows}
    unmatched_rows = sorted(
        (row for name, row in facts_by_channel.items() if name not in all_channel_names),
        key=lambda row: row["paid_amount"],
        reverse=True,
    )
    channel_rows.extend(
        {
            "channel_code": None,
            "channel_name": row["channel"],
            "category": "未匹配渠道",
            "channel_type": "未匹配渠道",
            "platform": "未设置",
            "owner": "-",
            "authorized": False,
            "orders": _int(row["orders"]),
            "paid_amount": row_paid_amount,
            "quantity": _int(row["quantity"]),
            "share": row_paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
            "avg_order_amount": row_paid_amount / _int(row["orders"]) if _int(row["orders"]) else 0,
            "is_online": is_online_sales_channel("未匹配渠道", "未设置", row["channel"]),
            "matched": False,
        }
        for row in unmatched_rows
        for row_paid_amount in [_number(row["paid_amount"])]
    )
    channel_rows.sort(key=lambda row: row["paid_amount"], reverse=True)

    def summarize_channels(field: str, include_unset: bool = True) -> list[dict]:
        grouped: dict[str, dict] = {}
        for row in channel_rows:
            key = row[field]
            if not include_unset and key == "未设置":
                continue
            item = grouped.setdefault(
                key,
                {field: key, "channels": 0, "active_channels": 0, "orders": 0, "paid_amount": 0.0, "quantity": 0},
            )
            item["channels"] += 1
            item["active_channels"] += 1 if row["orders"] > 0 else 0
            item["orders"] += row["orders"]
            item["paid_amount"] += row["paid_amount"]
            item["quantity"] += row["quantity"]
        return sorted(grouped.values(), key=lambda row: row["paid_amount"], reverse=True)

    type_summary = summarize_channels("channel_type")
    platform_summary = summarize_channels("platform", include_unset=False)[:12]

    data = {
        **meta,
        "summary": summary,
        "channel_summary": {
            "total_channels": len(channel_rows),
            "active_channels": sum(1 for row in channel_rows if row["orders"] > 0),
            "authorized_channels": sum(1 for row in channel_rows if row["authorized"]),
            "unmatched_sales_channels": len(unmatched_rows),
        },
        "trend": trend,
        "type_summary": [
            {
                "channel_type": row["channel_type"],
                "channels": _int(row["channels"]),
                "active_channels": _int(row["active_channels"]),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in type_summary
        ],
        "platform_summary": [
            {
                "platform": row["platform"],
                "channels": _int(row["channels"]),
                "active_channels": _int(row["active_channels"]),
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in platform_summary
        ],
        "rows": channel_rows,
        "unmatched_channels": [
            {
                "channel": row["channel"],
                "orders": _int(row["orders"]),
                "paid_amount": _number(row["paid_amount"]),
                "quantity": _int(row["quantity"]),
                "share": _number(row["paid_amount"]) / total_paid_amount * 100 if total_paid_amount else 0,
            }
            for row in unmatched_rows
        ],
        "filter_options": {
            "channel_types": channel_types,
            "platforms": platforms,
        },
    }
    return _cached_ok(cache_key, data)


@router.get("/channel-customer-analysis")
def sales_channel_customer_analysis(
    response: Response,
    channel_name: str = Query(..., min_length=1),
    range: str = Query("this_year"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    """Drill an offline sales channel down to customer-level sales performance."""
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "channel-customer-analysis-v1",
        channel_name=channel_name,
        range=range,
        start_date=start_date,
        end_date=end_date,
        keyword=keyword,
        page=page,
        page_size=page_size,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        owner = db.execute(
            text(
                """
                SELECT COALESCE(NULLIF(TRIM(`负责人`), ''), '-')
                FROM `渠道列表`
                WHERE `渠道名称` = :channel_name
                LIMIT 1
                """
            ),
            {"channel_name": channel_name.strip()},
        ).scalar()
        if AdsSessionLocal is None:
            raise HTTPException(status_code=503, detail="ADS database is not configured")
        with AdsSessionLocal() as ads_db:
            batch = latest_ready_sales_batch(ads_db)
            data = load_sales_channel_customer_from_ads(
                ads_db,
                batch,
                _ads_period_meta(batch, range, start_date, end_date),
                channel_name,
                owner or "-",
                keyword,
                page,
                page_size,
            )
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "channel_name": channel_name.strip(),
                "owner": "-",
                "summary": {"customers": 0, "orders": 0, "quantity": 0, "paid_amount": 0},
                "pagination": {"page": page, "page_size": page_size, "total": 0},
                "rows": [],
            },
        )

    params["channel_name"] = channel_name.strip()
    customer_filter = ""
    if keyword and keyword.strip():
        params["customer_keyword"] = f"%{keyword.strip()}%"
        customer_filter = """
            WHERE customer_code LIKE :customer_keyword
               OR customer_name LIKE :customer_keyword
        """

    customer_group_sql = f"""
        SELECT
          COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置') AS customer_code,
          COALESCE(o.customer_name, '未命名客户') AS customer_name,
          COUNT(DISTINCT l.`订单编号`) AS orders,
          SUM(COALESCE(l.`数量`, 0)) AS quantity,
          SUM(COALESCE(l.`分摊后金额`, 0)) AS paid_amount
        FROM `dwd`.`销售单明细账_品牌补全` l
        LEFT JOIN (
          SELECT
            `订单编号`,
            MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
            MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
          FROM {SALES_ORDER_TABLE_SQL}
          WHERE `下单时间` >= :start_date
            AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') = :channel_name
          GROUP BY `订单编号`
        ) o ON o.`订单编号` = l.`订单编号`
        WHERE l.`下单时间` >= :start_date
          AND l.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
          AND COALESCE(NULLIF(l.`销售渠道`, ''), '未归类') = :channel_name
        GROUP BY
          COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code, '未设置'),
          COALESCE(o.customer_name, '未命名客户')
    """
    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(*) AS customers,
              SUM(customer_sales.orders) AS orders,
              SUM(customer_sales.quantity) AS quantity,
              SUM(customer_sales.paid_amount) AS paid_amount
            FROM ({customer_group_sql}) customer_sales
            {customer_filter}
            """
        ),
        params,
    ).mappings().one()
    total = _int(summary_row["customers"])
    total_paid_amount = _number(summary_row["paid_amount"])
    row_params = {
        **params,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    }
    rows = db.execute(
        text(
            f"""
            SELECT customer_sales.*
            FROM ({customer_group_sql}) customer_sales
            {customer_filter}
            ORDER BY customer_sales.paid_amount DESC, customer_sales.quantity DESC, customer_sales.customer_code
            LIMIT :limit OFFSET :offset
            """
        ),
        row_params,
    ).mappings().all()
    owner = db.execute(
        text(
            """
            SELECT COALESCE(NULLIF(TRIM(`负责人`), ''), '-')
            FROM `渠道列表`
            WHERE `渠道名称` = :channel_name
            LIMIT 1
            """
        ),
        params,
    ).scalar()
    data = {
        **meta,
        "channel_name": channel_name.strip(),
        "owner": owner or "-",
        "summary": {
            "customers": total,
            "orders": _int(summary_row["orders"]),
            "quantity": _int(summary_row["quantity"]),
            "paid_amount": total_paid_amount,
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "rows": [
            {
                "customer_code": row["customer_code"],
                "customer_name": row["customer_name"],
                "orders": row_orders,
                "quantity": _int(row["quantity"]),
                "paid_amount": row_paid_amount,
                "share": row_paid_amount / total_paid_amount * 100 if total_paid_amount else 0,
                "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
            }
            for row in rows
            for row_orders in [_int(row["orders"])]
            for row_paid_amount in [_number(row["paid_amount"])]
        ],
    }
    return _cached_ok(cache_key, data)


@router.get("/customer-analysis")
def sales_customer_analysis(
    response: Response,
    direction: str = Query("brand", pattern="^(brand|channel|owner)$"),
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    brand: str | None = Query(None),
    channel: str | None = Query(None),
    channel_type: str | None = Query(None),
    owner: str | None = Query(None),
    keyword: str | None = Query(None),
    frequency: str = Query("all", pattern="^(all|first|stable|high)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
    _export: bool = Depends(_normal_request_context),
) -> dict:
    """Customer quality, frequency and top-product analysis from sales detail data."""
    export_mode = _export is True
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "customer-analysis-v6",
        direction=direction,
        range=range,
        start_date=start_date,
        end_date=end_date,
        brand=brand,
        channel=channel,
        channel_type=channel_type,
        owner=owner,
        keyword=keyword,
        frequency=frequency,
        query_mode=query_mode,
        page=page,
        page_size=page_size,
    )
    cached = None if export_mode else _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _query_result(cache_key, {
            **meta,
            "direction": direction,
            "summary": {"customers": 0, "repeat_customers": 0, "repeat_rate": 0, "orders": 0, "quantity": 0, "paid_amount": 0, "identified_amount": 0, "identified_amount_rate": 0, "avg_order_amount": 0},
            "quality": {"identified_orders": 0, "unidentified_orders": 0, "identified_order_rate": 0, "grade": "C"},
            "frequency": [], "top_products": [], "options": {"brands": [], "channels": [], "channel_types": [], "owners": []},
            "pagination": {"page": page, "page_size": page_size, "total": 0}, "rows": [],
        }, export_mode)

    selected_scope = (
        (brand or "").strip() if direction == "brand"
        else (owner or "").strip() if direction == "owner"
        else (
            (channel or "").strip()
            or (channel_type or "").strip()
            or (owner or "").strip()
        )
    )
    if not selected_scope:
        brands = db.execute(text(f"""
            SELECT DISTINCT ({BRAND_EXPRESSION_SQL}) AS brand
            FROM {SALES_DETAIL_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            ORDER BY brand
        """), params).scalars().all()
        channels = db.execute(text("""
            SELECT DISTINCT COALESCE(NULLIF(TRIM(`渠道名称`), ''), '未归类')
            FROM `渠道列表`
            ORDER BY 1
        """)).scalars().all()
        channel_types = db.execute(text("""
            SELECT DISTINCT COALESCE(NULLIF(TRIM(`分类`), ''), '未分类')
            FROM `渠道列表`
            ORDER BY 1
        """)).scalars().all()
        owners = db.execute(text("""
            SELECT DISTINCT COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配')
            FROM `渠道列表`
            ORDER BY 1
        """)).scalars().all()
        return _query_result(cache_key, {
            **meta,
            "direction": direction,
            "scope_required": True,
            "summary": {"customers": 0, "repeat_customers": 0, "repeat_rate": 0, "orders": 0, "quantity": 0, "paid_amount": 0, "identified_amount": 0, "identified_amount_rate": 0, "avg_order_amount": 0},
            "quality": {"identified_orders": 0, "unidentified_orders": 0, "identified_order_rate": 0, "grade": "C"},
            "frequency": [], "top_products": [],
            "options": {
                "brands": [str(item) for item in brands if item],
                "channels": [str(item) for item in channels if item],
                "channel_types": [str(item) for item in channel_types if item],
                "owners": [str(item) for item in owners if item],
            },
            "pagination": {"page": page, "page_size": page_size, "total": 0}, "rows": [],
        }, export_mode)

    dimension_option_rows = db.execute(text("""
        SELECT DISTINCT
          COALESCE(NULLIF(TRIM(`渠道名称`), ''), '未归类') AS channel_name,
          COALESCE(NULLIF(TRIM(`分类`), ''), '未分类') AS channel_type,
          COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配') AS owner
        FROM `渠道列表`
        ORDER BY channel_name
    """)).mappings().all()
    channel_type_option_rows = [
        row for row in dimension_option_rows
        if direction != "channel"
        or not channel_type
        or str(row["channel_type"]) == channel_type.strip()
    ]
    channel_option_rows = [
        row for row in channel_type_option_rows
        if direction != "channel"
        or not owner
        or str(row["owner"]) == owner.strip()
    ]

    if query_mode in {"ads", "dual"} and AdsSessionLocal is not None:
        try:
            selected_channels: list[str] | None = None
            if direction == "channel" and channel and channel.strip():
                selected_channels = [channel.strip()]
            elif direction == "channel" and (
                (channel_type and channel_type.strip()) or (owner and owner.strip())
            ):
                channel_filters = []
                channel_params: dict[str, str] = {}
                if channel_type and channel_type.strip():
                    channel_filters.append(
                        "COALESCE(NULLIF(TRIM(`分类`), ''), '未分类') = :channel_type"
                    )
                    channel_params["channel_type"] = channel_type.strip()
                if owner and owner.strip():
                    channel_filters.append(
                        "COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配') = :channel_owner"
                    )
                    channel_params["channel_owner"] = owner.strip()
                selected_channels = [str(item) for item in db.execute(text(f"""
                    SELECT DISTINCT `渠道名称` FROM `渠道列表`
                    WHERE {' AND '.join(channel_filters)}
                """), channel_params).scalars().all() if item]
            elif direction == "owner" and owner and owner.strip():
                selected_channels = [str(item) for item in db.execute(text("""
                    SELECT DISTINCT `渠道名称` FROM `渠道列表`
                    WHERE COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配') = :owner
                """), {"owner": owner.strip()}).scalars().all() if item]
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_sales_batch(ads_db)
                ads_data = load_sales_customer_analysis_from_ads(
                    ads_db, batch, meta,
                    brand.strip() if direction == "brand" and brand else None,
                    selected_channels, keyword, frequency, page, page_size,
                )
                ads_brands = [str(item) for item in ads_db.execute(text("""
                    SELECT DISTINCT `brand` FROM `ads_sales_customer_daily`
                    WHERE `data_version` = :data_version AND `brand` <> '__all__'
                    ORDER BY `brand`
                """), {"data_version": batch.data_version}).scalars().all() if item]
            ads_data["direction"] = direction
            ads_data["options"] = {
                "brands": ads_brands,
                "channels": [str(row["channel_name"]) for row in channel_option_rows],
                "channel_types": sorted({str(row["channel_type"]) for row in dimension_option_rows}),
                "owners": sorted({str(row["owner"]) for row in channel_type_option_rows}),
            }
            response.headers["X-BI-Response-Source"] = "ads"
            return _query_result(cache_key, ads_data, export_mode)
        except Exception as exc:
            logger.warning("customer_analysis_ads_fallback error=%s", type(exc).__name__)

    response.headers["X-BI-Response-Source"] = "ods"

    filters = []
    brand_expr = BRAND_EXPRESSION_SQL
    if direction == "brand" and brand and brand.strip():
        params["brand"] = brand.strip()
        filters.append(f"({brand_expr}) = :brand")
    if direction == "channel" and channel and channel.strip():
        params["channel"] = channel.strip()
        filters.append("COALESCE(NULLIF(TRIM(l.`销售渠道`), ''), '未归类') = :channel")
    if direction == "channel" and channel_type and channel_type.strip():
        params["channel_type"] = channel_type.strip()
        filters.append("c.channel_type = :channel_type")
    if direction == "channel" and owner and owner.strip():
        params["channel_owner"] = owner.strip()
        filters.append("c.owner = :channel_owner")
    if direction == "owner" and owner and owner.strip():
        params["owner"] = owner.strip()
        filters.append("c.owner = :owner")
    filter_sql = "".join(f" AND {item}" for item in filters)

    base_sql = f"""
        SELECT
          l.`订单编号` AS order_id,
          DATE(l.`下单时间`) AS sales_date,
          COALESCE(NULLIF(TRIM(l.`销售渠道`), ''), '未归类') AS channel,
          ({brand_expr}) AS brand,
          COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code) AS customer_code,
          COALESCE(o.customer_name, '未命名客户') AS customer_name,
          l.`货品编号` AS product_code,
          l.`货品名称` AS product_name,
          COALESCE(l.`数量`, 0) AS quantity,
          COALESCE(l.`分摊后金额`, 0) AS paid_amount
        FROM {SALES_DETAIL_TABLE_SQL} l
        LEFT JOIN (
          SELECT `渠道名称`,
                 MAX(COALESCE(NULLIF(TRIM(`分类`), ''), '未分类')) AS channel_type,
                 MAX(COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配')) AS owner
          FROM `渠道列表`
          GROUP BY `渠道名称`
        ) c ON c.`渠道名称` = l.`销售渠道`
        LEFT JOIN (
          SELECT `订单编号`,
                 MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
                 MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
          FROM {SALES_ORDER_TABLE_SQL}
          WHERE `下单时间` >= :start_date
            AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            AND {ACTIVE_SALES_ORDER_SQL}
          GROUP BY `订单编号`
        ) o ON o.`订单编号` = l.`订单编号`
        WHERE l.`下单时间` >= :start_date
          AND l.`下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
          {filter_sql}
    """
    customer_group_sql = f"""
        SELECT customer_code,
               MAX(customer_name) AS customer_name,
               COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT sales_date) AS active_days,
               MIN(sales_date) AS first_order_date,
               MAX(sales_date) AS last_order_date,
               SUM(quantity) AS quantity,
               SUM(paid_amount) AS paid_amount
        FROM ({base_sql}) customer_detail
        WHERE customer_code IS NOT NULL AND customer_code <> ''
        GROUP BY customer_code
    """
    keyword_sql = ""
    if keyword and keyword.strip():
        params["keyword"] = f"%{keyword.strip()}%"
        keyword_sql = "WHERE customer_code LIKE :keyword OR customer_name LIKE :keyword"

    summary = db.execute(text(f"""
        SELECT COUNT(*) AS customers,
               SUM(CASE WHEN orders >= 2 THEN 1 ELSE 0 END) AS repeat_customers,
               SUM(orders) AS orders,
               SUM(quantity) AS quantity,
               SUM(paid_amount) AS paid_amount
        FROM ({customer_group_sql}) customers
        {keyword_sql}
    """), params).mappings().one()
    quality = db.execute(text(f"""
        SELECT COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT CASE WHEN customer_code IS NOT NULL AND customer_code <> '' THEN order_id END) AS identified_orders,
               SUM(paid_amount) AS paid_amount,
               SUM(CASE WHEN customer_code IS NOT NULL AND customer_code <> '' THEN paid_amount ELSE 0 END) AS identified_amount
        FROM ({base_sql}) quality_detail
    """), params).mappings().one()
    frequency_rows = db.execute(text(f"""
        SELECT CASE
                 WHEN orders = 1 THEN 'first'
                 WHEN orders BETWEEN 2 AND 3 THEN 'stable'
                 ELSE 'high'
               END AS bucket,
               CASE
                 WHEN orders = 1 THEN '首购客户'
                 WHEN orders BETWEEN 2 AND 3 THEN '稳定客户'
                 ELSE '高频客户'
               END AS label,
               COUNT(*) AS customers,
               SUM(paid_amount) AS paid_amount
        FROM ({customer_group_sql}) customers
        {keyword_sql}
        GROUP BY bucket, label
        ORDER BY MIN(orders)
    """), params).mappings().all()
    top_products = db.execute(text(f"""
        SELECT COALESCE(NULLIF(product_code, ''), '-') AS product_code,
               COALESCE(NULLIF(product_name, ''), '未命名货品') AS product_name,
               COUNT(DISTINCT order_id) AS orders,
               COUNT(DISTINCT customer_code) AS customers,
               SUM(quantity) AS quantity,
               SUM(paid_amount) AS paid_amount
        FROM ({base_sql}) product_detail
        WHERE customer_code IS NOT NULL AND customer_code <> ''
        GROUP BY COALESCE(NULLIF(product_code, ''), '-'), COALESCE(NULLIF(product_name, ''), '未命名货品')
        ORDER BY paid_amount DESC, quantity DESC
        LIMIT 15
    """), params).mappings().all()
    total = _int(summary["customers"])
    repeat_customers = _int(summary["repeat_customers"])
    total_orders = _int(quality["orders"])
    identified_orders = _int(quality["identified_orders"])
    total_amount = _number(quality["paid_amount"])
    identified_amount = _number(quality["identified_amount"])
    row_filters = []
    if keyword_sql:
        row_filters.append("(customer_code LIKE :keyword OR customer_name LIKE :keyword)")
    frequency_conditions = {
        "first": "orders = 1",
        "stable": "orders BETWEEN 2 AND 3",
        "high": "orders >= 4",
    }
    if frequency in frequency_conditions:
        row_filters.append(frequency_conditions[frequency])
    row_filter_sql = "WHERE " + " AND ".join(row_filters) if row_filters else ""
    filtered_total = total if frequency == "all" else next(
        (_int(row["customers"]) for row in frequency_rows if row["bucket"] == frequency),
        0,
    )
    row_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    rows = db.execute(text(f"""
        SELECT * FROM ({customer_group_sql}) customers
        {row_filter_sql}
        ORDER BY paid_amount DESC, orders DESC, customer_code
        LIMIT :limit OFFSET :offset
    """), row_params).mappings().all()
    identified_order_rate = identified_orders / total_orders * 100 if total_orders else 0
    quality_grade = "A" if identified_order_rate >= 90 else "B" if identified_order_rate >= 60 else "C"
    ods_brand_options = []
    if direction == "brand":
        ods_brand_options = [str(item) for item in db.execute(text(f"""
            SELECT DISTINCT ({BRAND_EXPRESSION_SQL}) AS brand
            FROM {SALES_DETAIL_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
            ORDER BY brand
        """), params).scalars().all() if item]
    data = {
        **meta,
        "direction": direction,
        "scope_required": False,
        "summary": {
            "customers": total,
            "repeat_customers": repeat_customers,
            "repeat_rate": repeat_customers / total * 100 if total else 0,
            "orders": _int(summary["orders"]),
            "quantity": _int(summary["quantity"]),
            "paid_amount": _number(summary["paid_amount"]),
            "identified_amount": identified_amount,
            "identified_amount_rate": identified_amount / total_amount * 100 if total_amount else 0,
            "avg_order_amount": _number(summary["paid_amount"]) / _int(summary["orders"]) if _int(summary["orders"]) else 0,
        },
        "quality": {
            "identified_orders": identified_orders,
            "unidentified_orders": max(0, total_orders - identified_orders),
            "identified_order_rate": identified_order_rate,
            "grade": quality_grade,
        },
        "frequency": [{"bucket": row["bucket"], "label": row["label"], "customers": _int(row["customers"]), "paid_amount": _number(row["paid_amount"])} for row in frequency_rows],
        "top_products": [{"product_code": row["product_code"], "product_name": row["product_name"], "orders": _int(row["orders"]), "customers": _int(row["customers"]), "quantity": _int(row["quantity"]), "paid_amount": _number(row["paid_amount"])} for row in top_products],
        "options": {
            "brands": ods_brand_options,
            "channels": [str(row["channel_name"]) for row in channel_option_rows],
            "channel_types": sorted({str(row["channel_type"]) for row in dimension_option_rows}),
            "owners": sorted({str(row["owner"]) for row in channel_type_option_rows}),
        },
        "pagination": {"page": page, "page_size": page_size, "total": filtered_total},
        "rows": [{
            "customer_code": row["customer_code"], "customer_name": row["customer_name"],
            "orders": _int(row["orders"]), "active_days": _int(row["active_days"]),
            "first_order_date": row["first_order_date"].isoformat() if row["first_order_date"] else None,
            "last_order_date": row["last_order_date"].isoformat() if row["last_order_date"] else None,
            "avg_interval_days": max(0, (row["last_order_date"] - row["first_order_date"]).days / (_int(row["orders"]) - 1)) if _int(row["orders"]) > 1 else None,
            "quantity": _int(row["quantity"]), "paid_amount": _number(row["paid_amount"]),
            "avg_order_amount": _number(row["paid_amount"]) / _int(row["orders"]) if _int(row["orders"]) else 0,
        } for row in rows],
    }
    return _query_result(cache_key, data, export_mode)


@router.get("/customer-churn-alerts")
def sales_customer_churn_alerts(
    response: Response,
    direction: str = Query("brand", pattern="^(brand|channel|owner)$"),
    brand: str | None = Query(None),
    channel: str | None = Query(None),
    channel_type: str | None = Query(None),
    owner: str | None = Query(None),
    keyword: str | None = Query(None),
    inactive_months: int = Query(3),
    min_historical_orders: int = Query(4, ge=2, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
    _export: bool = Depends(_normal_request_context),
) -> dict:
    """Customers who ordered frequently before the selected inactivity window."""
    export_mode = _export is True
    if inactive_months not in {3, 6, 12}:
        raise HTTPException(status_code=422, detail="未下单周期仅支持 3、6 或 12 个月")

    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key(
        "customer-churn-alerts-v1",
        direction=direction,
        brand=brand,
        channel=channel,
        channel_type=channel_type,
        owner=owner,
        keyword=keyword,
        inactive_months=inactive_months,
        min_historical_orders=min_historical_orders,
        query_mode=query_mode,
        page=page,
        page_size=page_size,
    )
    cached = None if export_mode else _get_sales_cache(cache_key)
    if cached is not None:
        return ok(cached)

    max_date = db.execute(text("SELECT MAX(`下单时间`) FROM `dwd`.`销售单明细账_品牌补全`")).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return _query_result(cache_key, {
            "as_of": None, "scope_required": False,
            "summary": {"alert_customers": 0, "critical_customers": 0, "high_value_customers": 0, "historical_amount": 0},
            "pagination": {"page": page, "page_size": page_size, "total": 0}, "rows": [],
            "options": {"brands": [], "channels": [], "channel_types": [], "owners": []},
        }, export_mode)

    def subtract_months(value: date, months: int) -> date:
        target_month = value.month - months
        target_year = value.year + (target_month - 1) // 12
        target_month = (target_month - 1) % 12 + 1
        month_days = [31, 29 if target_year % 4 == 0 and (target_year % 100 != 0 or target_year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        return date(target_year, target_month, min(value.day, month_days[target_month - 1]))

    cutoff_date = subtract_months(as_of, inactive_months)
    history_start = subtract_months(cutoff_date, 12)
    result_as_of = as_of
    result_cutoff_date = cutoff_date
    selected_scope = (
        (brand or "").strip() if direction == "brand"
        else (owner or "").strip() if direction == "owner"
        else ((channel or "").strip() or (channel_type or "").strip())
    )

    dimension_rows = db.execute(text("""
        SELECT DISTINCT
          COALESCE(NULLIF(TRIM(`渠道名称`), ''), '未归类') AS channel_name,
          COALESCE(NULLIF(TRIM(`分类`), ''), '未分类') AS channel_type,
          COALESCE(NULLIF(TRIM(`负责人`), ''), '未分配') AS owner
        FROM `渠道列表`
        ORDER BY channel_name
    """)).mappings().all()
    option_channels = [str(row["channel_name"]) for row in dimension_rows]
    option_channel_types = sorted({str(row["channel_type"]) for row in dimension_rows})
    option_owners = sorted({str(row["owner"]) for row in dimension_rows})

    if direction in {"brand", "owner"} and not selected_scope:
        brands = db.execute(text(f"""
            SELECT DISTINCT ({BRAND_EXPRESSION_SQL}) AS brand
            FROM {SALES_DETAIL_TABLE_SQL}
            WHERE `下单时间` >= :history_start
              AND `下单时间` < DATE_ADD(:as_of, INTERVAL 1 DAY)
            ORDER BY brand
        """), {"history_start": history_start, "as_of": as_of}).scalars().all()
        return _query_result(cache_key, {
            "as_of": as_of.isoformat(), "cutoff_date": cutoff_date.isoformat(),
            "history_start": history_start.isoformat(), "history_end": (cutoff_date - timedelta(days=1)).isoformat(),
            "scope_required": True,
            "summary": {"alert_customers": 0, "critical_customers": 0, "high_value_customers": 0, "historical_amount": 0},
            "pagination": {"page": page, "page_size": page_size, "total": 0}, "rows": [],
            "options": {"brands": [str(item) for item in brands if item], "channels": option_channels, "channel_types": option_channel_types, "owners": option_owners},
        }, export_mode)

    selected_channels: list[str] | None = None
    if direction == "channel" and channel and channel.strip():
        selected_channels = [channel.strip()]
    elif direction == "channel" and channel_type and channel_type.strip():
        selected_channels = [str(row["channel_name"]) for row in dimension_rows if str(row["channel_type"]) == channel_type.strip()]
    elif direction == "owner" and owner and owner.strip():
        selected_channels = [str(row["channel_name"]) for row in dimension_rows if str(row["owner"]) == owner.strip()]

    params: dict = {
        "history_start": history_start,
        "cutoff_date": cutoff_date,
        "as_of": as_of,
        "min_historical_orders": min_historical_orders,
    }
    source_sql = ""
    ads_brands: list[str] = []
    used_ads = False
    result_history_start = history_start
    if query_mode in {"ads", "dual"} and AdsSessionLocal is not None:
        try:
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_sales_batch(ads_db)
                ads_as_of = min(as_of, batch.source_end_date)
                ads_cutoff_date = subtract_months(ads_as_of, inactive_months)
                ads_history_start = subtract_months(ads_cutoff_date, 12)
                if batch.source_start_date >= ads_cutoff_date:
                    raise AdsDataUnavailable("ADS batch does not cover churn history")
                ads_result_history_start = max(ads_history_start, batch.source_start_date)
                ads_params = dict(params)
                ads_params.update({
                    "history_start": ads_result_history_start,
                    "cutoff_date": ads_cutoff_date,
                    "as_of": ads_as_of,
                    "data_version": batch.data_version,
                    "brand": brand.strip() if direction == "brand" and brand else "__all__",
                })
                channel_filter = ""
                if selected_channels:
                    ads_params["channel_0"] = selected_channels[0]
                    channel_tokens = [":channel_0"]
                    for index, value in enumerate(selected_channels[1:], start=1):
                        ads_params[f"channel_{index}"] = value
                        channel_tokens.append(f":channel_{index}")
                    channel_filter = f"AND `channel` IN ({', '.join(channel_tokens)})"
                source_sql = f"""
                    SELECT `sales_date`, `customer_code`, `customer_name`, `orders`, `quantity`, `paid_amount`
                    FROM `ads_sales_customer_daily`
                    WHERE `data_version` = :data_version
                      AND `sales_date` BETWEEN :history_start AND :as_of
                      AND `brand` = :brand {channel_filter}
                """
                ads_brands = [str(item) for item in ads_db.execute(text("""
                    SELECT DISTINCT `brand` FROM `ads_sales_customer_daily`
                    WHERE `data_version` = :data_version AND `brand` <> '__all__' ORDER BY `brand`
                """), {"data_version": batch.data_version}).scalars().all() if item]
                result_db = ads_db
                used_ads = True
                response.headers["X-BI-Response-Source"] = "ads"
                result = _customer_churn_result(
                    result_db, source_sql, ads_params, keyword, page, page_size, ads_as_of
                )
                result_as_of = ads_as_of
                result_cutoff_date = ads_cutoff_date
                result_history_start = ads_result_history_start
        except Exception as exc:
            logger.warning("customer_churn_ads_fallback error=%s", type(exc).__name__)
            used_ads = False

    if not used_ads:
        response.headers["X-BI-Response-Source"] = "ods"
        filters = []
        if direction == "brand" and brand and brand.strip():
            params["brand"] = brand.strip()
            filters.append(f"({BRAND_EXPRESSION_SQL}) = :brand")
        if selected_channels:
            channel_tokens = []
            for index, value in enumerate(selected_channels):
                params[f"channel_{index}"] = value
                channel_tokens.append(f":channel_{index}")
            filters.append(f"COALESCE(NULLIF(TRIM(l.`销售渠道`), ''), '未归类') IN ({', '.join(channel_tokens)})")
        filter_sql = "".join(f" AND {item}" for item in filters)
        source_sql = f"""
            SELECT DATE(l.`下单时间`) AS sales_date,
                   COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code) AS customer_code,
                   MAX(COALESCE(o.customer_name, '未命名客户')) AS customer_name,
                   COUNT(DISTINCT l.`订单编号`) AS orders,
                   SUM(COALESCE(l.`数量`, 0)) AS quantity,
                   SUM(COALESCE(l.`分摊后金额`, 0)) AS paid_amount
            FROM {SALES_DETAIL_TABLE_SQL} l
            LEFT JOIN (
              SELECT `订单编号`, MAX(NULLIF(TRIM(`客户编号`), '')) AS customer_code,
                     MAX(NULLIF(TRIM(`客户名称`), '')) AS customer_name
              FROM {SALES_ORDER_TABLE_SQL}
              WHERE `下单时间` >= :history_start AND `下单时间` < DATE_ADD(:as_of, INTERVAL 1 DAY)
                AND {ACTIVE_SALES_ORDER_SQL}
              GROUP BY `订单编号`
            ) o ON o.`订单编号` = l.`订单编号`
            WHERE l.`下单时间` >= :history_start AND l.`下单时间` < DATE_ADD(:as_of, INTERVAL 1 DAY)
              {filter_sql}
            GROUP BY DATE(l.`下单时间`), COALESCE(NULLIF(TRIM(l.`客户编号`), ''), o.customer_code)
        """
        result = _customer_churn_result(db, source_sql, params, keyword, page, page_size, as_of)

    result.update({
        "as_of": result_as_of.isoformat(), "cutoff_date": result_cutoff_date.isoformat(),
        "history_start": result_history_start.isoformat(), "history_end": (result_cutoff_date - timedelta(days=1)).isoformat(),
        "inactive_months": inactive_months, "min_historical_orders": min_historical_orders,
        "scope_required": False,
        "options": {"brands": ads_brands if used_ads else ([brand] if brand else []), "channels": option_channels, "channel_types": option_channel_types, "owners": option_owners},
    })
    return _query_result(cache_key, result, export_mode)


def _customer_churn_result(
    db: Session,
    source_sql: str,
    params: dict,
    keyword: str | None,
    page: int,
    page_size: int,
    as_of: date,
) -> dict:
    customer_sql = f"""
        SELECT customer_code, MAX(customer_name) AS customer_name,
               SUM(CASE WHEN sales_date < :cutoff_date THEN orders ELSE 0 END) AS historical_orders,
               SUM(CASE WHEN sales_date >= :cutoff_date THEN orders ELSE 0 END) AS recent_orders,
               COUNT(DISTINCT CASE WHEN sales_date < :cutoff_date THEN sales_date END) AS active_days,
               MIN(CASE WHEN sales_date < :cutoff_date THEN sales_date END) AS first_order_date,
               MAX(CASE WHEN sales_date < :cutoff_date THEN sales_date END) AS last_order_date,
               SUM(CASE WHEN sales_date < :cutoff_date THEN quantity ELSE 0 END) AS historical_quantity,
               SUM(CASE WHEN sales_date < :cutoff_date THEN paid_amount ELSE 0 END) AS historical_amount
        FROM ({source_sql}) daily
        WHERE customer_code IS NOT NULL AND customer_code <> ''
        GROUP BY customer_code
        HAVING historical_orders >= :min_historical_orders AND recent_orders = 0
    """
    filters = []
    if keyword and keyword.strip():
        params["keyword"] = f"%{keyword.strip()}%"
        filters.append("(customer_code LIKE :keyword OR customer_name LIKE :keyword)")
    filter_sql = "WHERE " + " AND ".join(filters) if filters else ""
    offset = (page - 1) * page_size
    params["page_size"] = page_size
    params["offset"] = offset
    rows = db.execute(text(f"""
        WITH eligible AS ({customer_sql}),
        enriched AS (
          SELECT *, DATEDIFF(:as_of, last_order_date) AS inactive_days,
                 CASE WHEN DATEDIFF(:as_of, last_order_date) >= 365 THEN 'critical'
                      WHEN DATEDIFF(:as_of, last_order_date) >= 180 THEN 'high' ELSE 'watch' END AS alert_level,
                 COUNT(*) OVER () AS total_customers,
                 SUM(historical_amount) OVER () AS total_historical_amount,
                 AVG(historical_amount) OVER () AS avg_historical_amount,
                 SUM(CASE WHEN DATEDIFF(:as_of, last_order_date) >= 365 THEN 1 ELSE 0 END) OVER () AS critical_customers
          FROM eligible {filter_sql}
        )
        SELECT *,
               SUM(CASE WHEN historical_amount >= avg_historical_amount THEN 1 ELSE 0 END) OVER () AS high_value_customers
        FROM enriched
        ORDER BY historical_amount DESC, historical_orders DESC, last_order_date
        LIMIT :page_size OFFSET :offset
    """), params).mappings().all()
    first_row = rows[0] if rows else {}
    total = _int(first_row.get("total_customers"))
    historical_amount = _number(first_row.get("total_historical_amount"))
    avg_amount = _number(first_row.get("avg_historical_amount"))
    high_value = _int(first_row.get("high_value_customers"))
    critical = _int(first_row.get("critical_customers"))
    return {
        "summary": {
            "alert_customers": total,
            "critical_customers": critical,
            "high_value_customers": _int(high_value),
            "historical_amount": historical_amount,
        },
        "pagination": {"page": page, "page_size": page_size, "total": total},
        "rows": [{
            "customer_code": row["customer_code"], "customer_name": row["customer_name"],
            "historical_orders": _int(row["historical_orders"]), "active_days": _int(row["active_days"]),
            "last_order_date": row["last_order_date"].isoformat() if row["last_order_date"] else None,
            "avg_interval_days": max(0, (row["last_order_date"] - row["first_order_date"]).days / (_int(row["historical_orders"]) - 1)) if _int(row["historical_orders"]) > 1 else None,
            "inactive_days": _int(row["inactive_days"]), "alert_level": row["alert_level"],
            "historical_quantity": _int(row["historical_quantity"]), "historical_amount": _number(row["historical_amount"]),
            "is_high_value": _number(row["historical_amount"]) >= avg_amount,
        } for row in rows],
    }


@router.get("/brand-channel-analysis")
def sales_brand_channel_analysis(
    response: Response,
    brand: str = Query(..., min_length=1),
    range: str = Query("last_30"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    channel_type: list[str] | None = Query(None),
    channel_name: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    selected_product_types = list(
        dict.fromkeys(item.strip() for item in product_type or [] if item.strip() in {"正装", "小样"})
    )
    cache_key = _sales_cache_key(
        "brand-channel-analysis-v4",
        brand=brand,
        range=range,
        start_date=start_date,
        end_date=end_date,
        channel_type=channel_type,
        channel_name=channel_name,
        product_type=selected_product_types,
        query_mode=query_mode,
    )
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        selected_channel_types = list(
            dict.fromkeys(item.strip() for item in channel_type or [] if item.strip())
        )
        selected_channel_names = list(
            dict.fromkeys(item.strip() for item in channel_name or [] if item.strip())
        )
        dimension_rows = [
            dict(row)
            for row in db.execute(
                text(
                    """
                    SELECT
                      `渠道编号` AS channel_code,
                      `渠道名称` AS channel_name,
                      COALESCE(NULLIF(`分类`, ''), '未分类') AS channel_type,
                      COALESCE(NULLIF(`渠道类型`, ''), '未分类') AS source_channel_type,
                      COALESCE(NULLIF(`线上平台`, ''), '未设置') AS platform,
                      COALESCE(NULLIF(`负责人`, ''), '-') AS owner
                    FROM `渠道列表`
                    WHERE NULLIF(`渠道名称`, '') IS NOT NULL
                    """
                )
            ).mappings().all()
        ]
        if AdsSessionLocal is None:
            raise HTTPException(status_code=503, detail="ADS database is not configured")
        with AdsSessionLocal() as ads_db:
            batch = latest_ready_sales_batch(ads_db)
            data = load_sales_brand_channel_from_ads(
                ads_db,
                batch,
                _ads_period_meta(batch, range, start_date, end_date),
                brand,
                selected_product_types,
                selected_channel_types,
                selected_channel_names,
                dimension_rows,
            )
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    response.headers["X-BI-Response-Source"] = "ods"
    params, meta = _resolve_detail_sales_period(db, range, start_date, end_date)
    if params is None:
        return _cached_ok(
            cache_key,
            {
                **meta,
                "brand": brand,
                "summary": {
                    "paid_amount": 0,
                    "orders": 0,
                    "quantity": 0,
                    "avg_order_amount": 0,
                    "avg_unit_price": 0,
                },
                "trend": [],
                "channel_types": [],
                "platforms": [],
                "channels": [],
                "products": [],
                "salesperson_product_types": [],
                "sales_contribution": {
                    "online": {"paid_amount": 0, "quantity": 0},
                    "offline": {"paid_amount": 0, "quantity": 0},
                    "paid_amount_difference": 0,
                    "quantity_difference": 0,
                },
                "unmatched_channels": [],
                "filter_options": {
                    "channel_types": [],
                    "channel_names": [],
                },
            },
        )

    params["brand"] = brand.strip()
    selected_channel_types = list(dict.fromkeys(item.strip() for item in channel_type or [] if item.strip()))
    selected_channel_names = list(dict.fromkeys(item.strip() for item in channel_name or [] if item.strip()))
    channel_type_params = []
    for index, item in enumerate(selected_channel_types):
        param_name = f"channel_type_{index}"
        params[param_name] = item
        channel_type_params.append(f":{param_name}")
    channel_name_params = []
    for index, item in enumerate(selected_channel_names):
        param_name = f"channel_name_{index}"
        params[param_name] = item
        channel_name_params.append(f":{param_name}")
    brand_expr = BRAND_EXPRESSION_SQL
    fact_where = f"""
        `下单时间` >= :start_date
        AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
        AND {brand_expr} = :brand
    """
    if selected_channel_types:
        fact_where += f"""
        AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN (
          SELECT `渠道名称`
          FROM `渠道列表`
          WHERE COALESCE(NULLIF(`分类`, ''), '未分类') IN ({", ".join(channel_type_params)})
        )
        """
    if selected_channel_names:
        fact_where += f"""
        AND COALESCE(NULLIF(`销售渠道`, ''), '未归类') IN ({", ".join(channel_name_params)})
        """
    if selected_product_types:
        product_type_params = []
        for index, item in enumerate(selected_product_types):
            param_name = f"product_type_{index}"
            params[param_name] = item
            product_type_params.append(f":{param_name}")
        fact_where += f"""
        AND COALESCE(NULLIF(TRIM(`货品分类`), ''), '未分类') IN ({", ".join(product_type_params)})
        """

    channel_dimension_where = []
    if selected_channel_types:
        channel_dimension_where.append(
            f"COALESCE(NULLIF(c.`分类`, ''), '未分类') IN ({', '.join(channel_type_params)})"
        )
    if selected_channel_names:
        channel_dimension_where.append(
            f"c.`渠道名称` IN ({', '.join(channel_name_params)})"
        )
    channel_dimension_clause = (
        f"WHERE {' AND '.join(channel_dimension_where)}" if channel_dimension_where else ""
    )
    platform_dimension_where = [
        *channel_dimension_where,
        "NULLIF(TRIM(c.`线上平台`), '') IS NOT NULL",
    ]
    platform_dimension_clause = f"WHERE {' AND '.join(platform_dimension_where)}"

    summary_row = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {fact_where}
            """
        ),
        params,
    ).mappings().one()
    orders = _int(summary_row["orders"])
    quantity = _int(summary_row["quantity"])
    paid_amount = _number(summary_row["paid_amount"])

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS day,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {fact_where}
            GROUP BY DATE(`下单时间`)
            ORDER BY day
            """
        ),
        params,
    ).mappings().all()

    channel_fact_sql = f"""
        SELECT
          COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
          COUNT(*) AS detail_rows,
          COUNT(DISTINCT `订单编号`) AS orders,
          SUM(COALESCE(`数量`, 0)) AS quantity,
          SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
        FROM `dwd`.`销售单明细账_品牌补全`
        WHERE {fact_where}
        GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
    """

    channel_rows = db.execute(
        text(
            f"""
            SELECT
              c.`渠道编号` AS channel_code,
              c.`渠道名称` AS channel_name,
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS channel_type,
              COALESCE(NULLIF(c.`渠道类型`, ''), '未分类') AS source_channel_type,
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COALESCE(NULLIF(c.`负责人`, ''), '-') AS owner,
              COALESCE(f.detail_rows, 0) AS detail_rows,
              COALESCE(f.orders, 0) AS orders,
              COALESCE(f.quantity, 0) AS quantity,
              COALESCE(f.paid_amount, 0) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {channel_dimension_clause}
            ORDER BY paid_amount DESC, orders DESC, c.`渠道编号`
            """
        ),
        params,
    ).mappings().all()

    type_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(c.`分类`, ''), '未分类') AS channel_type,
              COUNT(*) AS channels,
              SUM(CASE WHEN COALESCE(f.orders, 0) > 0 THEN 1 ELSE 0 END) AS active_channels,
              SUM(COALESCE(f.orders, 0)) AS orders,
              SUM(COALESCE(f.quantity, 0)) AS quantity,
              SUM(COALESCE(f.paid_amount, 0)) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {channel_dimension_clause}
            GROUP BY COALESCE(NULLIF(c.`分类`, ''), '未分类')
            ORDER BY paid_amount DESC
            """
        ),
        params,
    ).mappings().all()

    platform_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(c.`线上平台`, ''), '未设置') AS platform,
              COUNT(*) AS channels,
              SUM(CASE WHEN COALESCE(f.orders, 0) > 0 THEN 1 ELSE 0 END) AS active_channels,
              SUM(COALESCE(f.orders, 0)) AS orders,
              SUM(COALESCE(f.quantity, 0)) AS quantity,
              SUM(COALESCE(f.paid_amount, 0)) AS paid_amount
            FROM `渠道列表` c
            LEFT JOIN ({channel_fact_sql}) f ON f.channel = c.`渠道名称`
            {platform_dimension_clause}
            GROUP BY COALESCE(NULLIF(c.`线上平台`, ''), '未设置')
            ORDER BY paid_amount DESC
            LIMIT 12
            """
        ),
        params,
    ).mappings().all()

    product_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`货品名称`, ''), '未命名商品') AS product,
              COUNT(DISTINCT `订单编号`) AS orders,
              SUM(COALESCE(`数量`, 0)) AS quantity,
              SUM(COALESCE(`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全`
            WHERE {fact_where}
            GROUP BY COALESCE(NULLIF(`货品名称`, ''), '未命名商品')
            ORDER BY paid_amount DESC
            LIMIT 20
            """
        ),
        params,
    ).mappings().all()

    salesperson_product_type_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(c.`负责人`), ''), '未设置') AS salesperson,
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类') AS product_type,
              SUM(COALESCE(s.`数量`, 0)) AS quantity,
              SUM(COALESCE(s.`分摊后金额`, 0)) AS paid_amount
            FROM `dwd`.`销售单明细账_品牌补全` s
            LEFT JOIN `渠道列表` c
              ON c.`渠道名称` = COALESCE(NULLIF(s.`销售渠道`, ''), '未归类')
            WHERE {fact_where}
              AND NULLIF(TRIM(s.`货品分类`), '') IN ('正装', '小样')
            GROUP BY
              COALESCE(NULLIF(TRIM(c.`负责人`), ''), '未设置'),
              COALESCE(NULLIF(TRIM(s.`货品分类`), ''), '未分类')
            ORDER BY salesperson, product_type
            """
        ),
        params,
    ).mappings().all()

    unmatched_rows = db.execute(
        text(
            f"""
            SELECT f.channel, f.orders, f.quantity, f.paid_amount
            FROM ({channel_fact_sql}) f
            LEFT JOIN `渠道列表` c ON c.`渠道名称` = f.channel
            WHERE c.`渠道名称` IS NULL
            ORDER BY f.paid_amount DESC
            """
        ),
        params,
    ).mappings().all()

    filter_option_rows = db.execute(
        text(
            """
            SELECT
              `渠道名称` AS channel_name,
              COALESCE(NULLIF(`分类`, ''), '未分类') AS channel_type
            FROM `渠道列表`
            WHERE NULLIF(`渠道名称`, '') IS NOT NULL
            ORDER BY channel_type, channel_name
            """
        )
    ).mappings().all()

    def dimension_row(row: dict, label_key: str) -> dict:
        row_paid_amount = _number(row["paid_amount"])
        row_orders = _int(row["orders"])
        row_quantity = _int(row["quantity"])
        return {
            label_key: row[label_key],
            "channels": _int(row["channels"]),
            "active_channels": _int(row["active_channels"]),
            "orders": row_orders,
            "quantity": row_quantity,
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
        }

    channel_data = [
        {
            "channel_code": row["channel_code"],
            "channel_name": row["channel_name"],
            "channel_type": row["channel_type"],
            "source_channel_type": row["source_channel_type"],
            "platform": row["platform"],
            "owner": row["owner"],
            "detail_rows": _int(row["detail_rows"]),
            "orders": row_orders,
            "quantity": row_quantity,
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / row_orders if row_orders else 0,
            "avg_unit_price": row_paid_amount / row_quantity if row_quantity else 0,
            "is_online": is_online_sales_channel(row["channel_type"], row["platform"], row["channel_name"]),
            "matched": True,
        }
        for row in channel_rows
        for row_orders in [_int(row["orders"])]
        for row_quantity in [_int(row["quantity"])]
        for row_paid_amount in [_number(row["paid_amount"])]
    ]
    channel_data.extend(
        {
            "channel_code": None,
            "channel_name": row["channel"],
            "channel_type": "未匹配渠道",
            "source_channel_type": "未匹配渠道",
            "platform": "未设置",
            "owner": "-",
            "detail_rows": 0,
            "orders": _int(row["orders"]),
            "quantity": _int(row["quantity"]),
            "paid_amount": row_paid_amount,
            "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
            "avg_order_amount": row_paid_amount / _int(row["orders"]) if _int(row["orders"]) else 0,
            "avg_unit_price": row_paid_amount / _int(row["quantity"]) if _int(row["quantity"]) else 0,
            "is_online": is_online_sales_channel("未匹配渠道", "未设置", row["channel"]),
            "matched": False,
        }
        for row in unmatched_rows
        for row_paid_amount in [_number(row["paid_amount"])]
    )
    channel_data.sort(key=lambda row: row["paid_amount"], reverse=True)
    online_channel_data = [row for row in channel_data if row["is_online"]]
    offline_channel_data = [row for row in channel_data if not row["is_online"]]
    online_paid_amount = sum(row["paid_amount"] for row in online_channel_data)
    offline_paid_amount = sum(row["paid_amount"] for row in offline_channel_data)
    online_quantity = sum(row["quantity"] for row in online_channel_data)
    offline_quantity = sum(row["quantity"] for row in offline_channel_data)

    salesperson_data: dict[str, dict] = {}
    for row in salesperson_product_type_rows:
        salesperson = row["salesperson"]
        item = salesperson_data.setdefault(
            salesperson,
            {
                "salesperson": salesperson,
                "regular_quantity": 0,
                "regular_paid_amount": 0.0,
                "sample_quantity": 0,
                "sample_paid_amount": 0.0,
            },
        )
        prefix = "regular" if row["product_type"] == "正装" else "sample"
        item[f"{prefix}_quantity"] += _int(row["quantity"])
        item[f"{prefix}_paid_amount"] += _number(row["paid_amount"])
    salesperson_product_types = []
    for item in salesperson_data.values():
        item["total_quantity"] = item["regular_quantity"] + item["sample_quantity"]
        item["total_paid_amount"] = item["regular_paid_amount"] + item["sample_paid_amount"]
        salesperson_product_types.append(item)
    salesperson_product_types.sort(key=lambda row: row["total_paid_amount"], reverse=True)

    data = {
        **meta,
        "brand": brand.strip(),
        "summary": {
            "paid_amount": paid_amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": paid_amount / orders if orders else 0,
            "avg_unit_price": paid_amount / quantity if quantity else 0,
        },
        "trend": [
            {
                "date": row["day"].isoformat(),
                "orders": _int(row["orders"]),
                "quantity": _int(row["quantity"]),
                "paid_amount": _number(row["paid_amount"]),
            }
            for row in trend_rows
        ],
        "channel_types": [dimension_row(row, "channel_type") for row in type_rows],
        "platforms": [dimension_row(row, "platform") for row in platform_rows],
        "channels": channel_data,
        "sales_contribution": {
            "online": {"paid_amount": online_paid_amount, "quantity": online_quantity},
            "offline": {"paid_amount": offline_paid_amount, "quantity": offline_quantity},
            "paid_amount_difference": paid_amount - online_paid_amount - offline_paid_amount,
            "quantity_difference": quantity - online_quantity - offline_quantity,
        },
        "salesperson_product_types": salesperson_product_types,
        "products": [
            {
                "rank": index + 1,
                "product": row["product"],
                "orders": row_orders,
                "quantity": row_quantity,
                "paid_amount": row_paid_amount,
                "share": row_paid_amount / paid_amount * 100 if paid_amount else 0,
                "avg_unit_price": row_paid_amount / row_quantity if row_quantity else 0,
            }
            for index, row in enumerate(product_rows)
            for row_orders in [_int(row["orders"])]
            for row_quantity in [_int(row["quantity"])]
            for row_paid_amount in [_number(row["paid_amount"])]
        ],
        "unmatched_channels": [
            {
                "channel": row["channel"],
                "orders": _int(row["orders"]),
                "quantity": _int(row["quantity"]),
                "paid_amount": _number(row["paid_amount"]),
            }
            for row in unmatched_rows
        ],
        "filter_options": {
            "channel_types": sorted({row["channel_type"] for row in filter_option_rows}),
            "channel_names": sorted({row["channel_name"] for row in filter_option_rows}),
        },
    }
    return _cached_ok(cache_key, data)
