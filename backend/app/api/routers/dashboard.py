from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routers.sales import (
    _cached_ok,
    _get_sales_cache,
    _sales_cache_key,
)
from app.core.config import settings
from app.db.ads import AdsSessionLocal
from app.db.ods import get_ods_db
from app.models.user import User
from app.schemas.common import ok
from app.services.sales_sources import (
    ACTIVE_SALES_ORDER_SQL,
    POSITIVE_SALES_ORDER_COUNT_SQL,
    SALES_ORDER_TABLE_SQL,
)
from app.services.sales_ads import (
    AdsDataUnavailable,
    latest_ready_sales_batch,
    load_dashboard_overview_from_ads,
)


router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CITY_COORDS = {
    "北京市": [116.4074, 39.9042],
    "上海市": [121.4737, 31.2304],
    "广州市": [113.2644, 23.1291],
    "深圳市": [114.0579, 22.5431],
    "杭州市": [120.1551, 30.2741],
    "南京市": [118.7969, 32.0603],
    "苏州市": [120.5853, 31.2989],
    "无锡市": [120.3119, 31.4912],
    "宁波市": [121.5503, 29.8746],
    "合肥市": [117.2272, 31.8206],
    "成都市": [104.0665, 30.5723],
    "重庆市": [106.5516, 29.563],
    "武汉市": [114.3054, 30.5931],
    "长沙市": [112.9388, 28.2282],
    "郑州市": [113.6254, 34.7466],
    "西安市": [108.9398, 34.3416],
    "天津市": [117.2008, 39.0842],
    "青岛市": [120.3826, 36.0671],
    "济南市": [117.1201, 36.6512],
    "福州市": [119.2965, 26.0745],
    "厦门市": [118.0894, 24.4798],
    "南昌市": [115.8582, 28.6829],
    "南宁市": [108.3669, 22.817],
    "昆明市": [102.8329, 24.8801],
    "贵阳市": [106.6302, 26.647],
    "石家庄市": [114.5149, 38.0428],
    "太原市": [112.5489, 37.8706],
    "沈阳市": [123.4315, 41.8057],
    "大连市": [121.6147, 38.914],
    "长春市": [125.3235, 43.8171],
    "哈尔滨市": [126.5349, 45.8038],
    "兰州市": [103.8343, 36.0611],
    "乌鲁木齐市": [87.6168, 43.8256],
    "海口市": [110.1983, 20.044],
    "三亚市": [109.5119, 18.2528],
    "珠海市": [113.5767, 22.2707],
    "东莞市": [113.7518, 23.0207],
    "佛山市": [113.1214, 23.0215],
    "中山市": [113.3926, 22.5176],
    "惠州市": [114.4168, 23.1115],
    "汕头市": [116.6819, 23.3541],
}


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


def _format_number(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def _format_million(value: float, digits: int = 2) -> str:
    return f"{value / 1_000_000:,.{digits}f}"


def _get_dashboard_ods_db():
    if settings.BI_QUERY_SOURCE == "ads":
        yield None
        return
    yield from get_ods_db()


@router.get("/overview")
def overview(
    response: Response,
    current_user: User = Depends(get_current_user),
    db: Session | None = Depends(_get_dashboard_ods_db),
) -> dict:
    query_mode = settings.BI_QUERY_SOURCE
    response.headers["X-BI-Query-Mode"] = query_mode
    cache_key = _sales_cache_key("dashboard-overview-v6", query_mode=query_mode)
    cached = _get_sales_cache(cache_key)
    if cached is not None:
        response.headers["X-BI-Response-Source"] = "ads" if query_mode == "ads" else "ods"
        return ok(cached)

    if query_mode == "ads":
        if AdsSessionLocal is None:
            raise HTTPException(status_code=503, detail="ADS database is not configured")
        try:
            with AdsSessionLocal() as ads_db:
                batch = latest_ready_sales_batch(ads_db)
                data = load_dashboard_overview_from_ads(ads_db, batch, CITY_COORDS)
        except AdsDataUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="ADS database is temporarily unavailable",
            ) from exc
        response.headers["X-BI-Response-Source"] = "ads"
        return _cached_ok(cache_key, data)

    if db is None:
        raise HTTPException(status_code=503, detail="ODS database is not configured")
    response.headers["X-BI-Response-Source"] = "ods"
    max_date = db.execute(
        text(f"SELECT MAX(`下单时间`) FROM {SALES_ORDER_TABLE_SQL} WHERE {ACTIVE_SALES_ORDER_SQL}")
    ).scalar()
    as_of = _as_date(max_date)
    if as_of is None:
        return _cached_ok(
            cache_key,
            {
                "as_of": None,
                "period": "近30天",
                "cards": [],
                "trend": {"days": [], "sales": [], "orders": []},
                "channels": [],
                "map_pies": [],
                "recent_orders": [],
            },
        )

    start_date = as_of - timedelta(days=29)
    trend_start = as_of - timedelta(days=6)
    params = {"start_date": start_date, "end_date": as_of, "trend_start": trend_start}

    summary_row = db.execute(
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

    paid_amount = _number(summary_row["paid_amount"])
    orders = _int(summary_row["orders"])
    quantity = _int(summary_row["quantity"])
    avg_order_amount = paid_amount / orders if orders else 0

    trend_rows = db.execute(
        text(
            f"""
            SELECT
              DATE(`下单时间`) AS day,
              {POSITIVE_SALES_ORDER_COUNT_SQL} AS orders,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :trend_start
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
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY paid_amount DESC
            LIMIT 6
            """
        ),
        params,
    ).mappings().all()

    city_channel_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(`市`, ''), '未填写') AS city,
              COALESCE(NULLIF(`销售渠道`, ''), '未归类') AS channel,
              SUM(COALESCE(`实付金额`, 0)) AS paid_amount
            FROM {SALES_ORDER_TABLE_SQL}
            WHERE `下单时间` >= :start_date
              AND `下单时间` < DATE_ADD(:end_date, INTERVAL 1 DAY)
              AND {ACTIVE_SALES_ORDER_SQL}
            GROUP BY
              COALESCE(NULLIF(`市`, ''), '未填写'),
              COALESCE(NULLIF(`销售渠道`, ''), '未归类')
            ORDER BY paid_amount DESC
            LIMIT 120
            """
        ),
        params,
    ).mappings().all()

    trend_by_day = {
        row["day"]: {"sales": _number(row["paid_amount"]), "orders": _int(row["orders"])}
        for row in trend_rows
    }
    days = [trend_start + timedelta(days=offset) for offset in range(7)]
    city_groups: dict[str, list[dict]] = {}
    for row in city_channel_rows:
        city = str(row["city"]).strip()
        if city not in CITY_COORDS:
            continue
        city_groups.setdefault(city, []).append(
            {"name": row["channel"], "value": round(_number(row["paid_amount"]), 2)}
        )

    map_pies = []
    for city, segments in city_groups.items():
        positive_segments = [segment for segment in segments if segment["value"] > 0]
        total = sum(segment["value"] for segment in positive_segments)
        if total <= 0:
            continue
        top_segments = sorted(positive_segments, key=lambda segment: segment["value"], reverse=True)[:3]
        other_value = total - sum(segment["value"] for segment in top_segments)
        if other_value > 0:
            top_segments.append({"name": "其他", "value": round(other_value, 2)})
        map_pies.append(
            {
                "name": city,
                "coord": CITY_COORDS[city],
                "total": round(total, 2),
                "segments": top_segments,
            }
        )
    map_pies = sorted(map_pies, key=lambda item: item["total"], reverse=True)[:8]

    data = {
        "as_of": as_of.isoformat(),
        "period": "近30天",
        "cards": [
            {"label": "近30天订单实付金额", "value": _format_million(paid_amount), "unit": "百万", "trend": f"截至 {as_of.isoformat()}"},
            {"label": "近30天销售", "value": _format_million(quantity), "unit": "百万", "trend": "净销售数量"},
        ],
        "trend": {
            "days": [day.strftime("%m-%d") for day in days],
            "sales": [trend_by_day.get(day, {"sales": 0})["sales"] for day in days],
            "orders": [trend_by_day.get(day, {"orders": 0})["orders"] for day in days],
        },
        "channels": [
            {"name": row["channel"], "value": round(_number(row["paid_amount"]), 2)}
            for row in channel_rows
        ],
        "map_pies": map_pies,
    }
    return _cached_ok(cache_key, data)
