from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.ods import get_ods_db
from app.models.user import User
from app.schemas.common import ok


router = APIRouter(prefix="/reservations", tags=["reservations"])


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _integer(value: object) -> int:
    return int(value or 0)


def _retention_rate(remaining: object, reserved: object) -> float | None:
    reserved_number = _number(reserved)
    if reserved_number <= 0:
        return None
    return round(_number(remaining) / reserved_number * 100, 2)


def _label(value: object, fallback: str = "未设置") -> str:
    normalized = str(value or "").strip()
    return normalized or fallback


def _date_text(value: object) -> str | None:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value) if value else None


def _multi_filter(
    values: tuple[str, ...],
    *,
    column: str,
    prefix: str,
    params: dict[str, object],
) -> str:
    if not values:
        return ""
    placeholders = []
    for index, value in enumerate(values):
        key = f"{prefix}_{index}"
        placeholders.append(f":{key}")
        params[key] = value
    return f"AND {column} IN ({', '.join(placeholders)})"


@router.get("/analysis")
def reservation_analysis(
    response: Response,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    status: list[str] | None = Query(None),
    warehouse: list[str] | None = Query(None),
    brand: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    department: list[str] | None = Query(None),
    applicant: list[str] | None = Query(None),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> dict:
    """Current reservation snapshot, grouped by source attributes and application time."""
    del current_user
    if start_date and end_date and end_date < start_date:
        start_date, end_date = end_date, start_date

    statuses = tuple(sorted({item.strip() for item in status or [] if item.strip()}))
    warehouses = tuple(sorted({item.strip() for item in warehouse or [] if item.strip()}))
    brands = tuple(sorted({item.strip() for item in brand or [] if item.strip()}))
    product_types = tuple(sorted({item.strip() for item in product_type or [] if item.strip()}))
    departments = tuple(sorted({item.strip() for item in department or [] if item.strip()}))
    applicants = tuple(sorted({item.strip() for item in applicant or [] if item.strip()}))
    normalized_keyword = (keyword or "").strip()

    params: dict[str, object] = {}
    filters = ["1 = 1"]
    if start_date:
        filters.append("h.`申请时间` >= :start_date")
        params["start_date"] = start_date
    if end_date:
        filters.append("h.`申请时间` < :end_exclusive")
        params["end_exclusive"] = end_date + timedelta(days=1)

    for clause in (
        _multi_filter(statuses, column="h.`状态`", prefix="status", params=params),
        _multi_filter(warehouses, column="h.`预留仓库`", prefix="warehouse", params=params),
        _multi_filter(brands, column="COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类')", prefix="brand", params=params),
        _multi_filter(product_types, column="COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')", prefix="product_type", params=params),
        _multi_filter(departments, column="COALESCE(NULLIF(TRIM(h.`申请部门`), ''), '未设置')", prefix="department", params=params),
        _multi_filter(applicants, column="COALESCE(NULLIF(TRIM(h.`申请人`), ''), '未设置')", prefix="applicant", params=params),
    ):
        if clause:
            filters.append(clause.removeprefix("AND "))
    if normalized_keyword:
        filters.append(
            "(h.`预留单号` LIKE :keyword OR h.`申请人` LIKE :keyword "
            "OR d.`货品编号` LIKE :keyword OR d.`货品名称` LIKE :keyword OR d.`条码` LIKE :keyword)"
        )
        params["keyword"] = f"%{normalized_keyword}%"

    where_sql = " AND ".join(f"({item})" for item in filters)
    joined_from = """
      FROM `预留单货品明细` d
      INNER JOIN `预留单查询` h ON h.`预留单ID` = d.`预留单ID`
    """

    option_rows = db.execute(
        text(
            """
            SELECT DISTINCT
              h.`状态` AS status,
              h.`预留仓库` AS warehouse,
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              COALESCE(NULLIF(TRIM(h.`申请部门`), ''), '未设置') AS department,
              COALESCE(NULLIF(TRIM(h.`申请人`), ''), '未设置') AS applicant
            FROM `预留单货品明细` d
            INNER JOIN `预留单查询` h ON h.`预留单ID` = d.`预留单ID`
            """
        )
    ).mappings().all()

    coverage = db.execute(
        text(
            """
            SELECT MIN(`申请时间`) AS min_date, MAX(`申请时间`) AS max_date,
                   MAX(GREATEST(COALESCE(`修改时间`, `申请时间`), COALESCE(`updatetime`, `申请时间`))) AS updated_at
            FROM `预留单查询`
            """
        )
    ).mappings().one()

    summary = db.execute(
        text(
            f"""
            SELECT
              COUNT(DISTINCT h.`预留单ID`) AS order_count,
              COUNT(DISTINCT CASE WHEN h.`状态` = '执行中' THEN h.`预留单ID` END) AS active_order_count,
              COUNT(DISTINCT NULLIF(d.`货品编号`, '')) AS sku_count,
              COALESCE(SUM(d.`预留数量`), 0) AS reserved_quantity,
              COALESCE(SUM(d.`剩余数量`), 0) AS remaining_quantity,
              COALESCE(SUM(d.`已用数量`), 0) AS used_quantity,
              COALESCE(SUM(d.`已释放数量`), 0) AS released_quantity
            {joined_from}
            WHERE {where_sql}
            """
        ),
        params,
    ).mappings().one()

    def grouped_rows(select_sql: str, group_sql: str, order_sql: str = "remaining_quantity DESC") -> list[dict]:
        return [
            dict(row)
            for row in db.execute(
                text(
                    f"""
                    SELECT {select_sql},
                      COUNT(DISTINCT h.`预留单ID`) AS order_count,
                      COALESCE(SUM(d.`预留数量`), 0) AS reserved_quantity,
                      COALESCE(SUM(d.`剩余数量`), 0) AS remaining_quantity,
                      COALESCE(SUM(d.`已用数量`), 0) AS used_quantity,
                      COALESCE(SUM(d.`已释放数量`), 0) AS released_quantity
                    {joined_from}
                    WHERE {where_sql}
                    GROUP BY {group_sql}
                    ORDER BY {order_sql}
                    """
                ),
                params,
            ).mappings().all()
        ]

    status_rows = grouped_rows("h.`状态` AS name", "h.`状态`")
    warehouse_rows = grouped_rows("COALESCE(NULLIF(TRIM(h.`预留仓库`), ''), '未设置') AS name", "COALESCE(NULLIF(TRIM(h.`预留仓库`), ''), '未设置')")
    brand_rows = grouped_rows("COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类') AS name", "COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类')")[:15]
    product_type_rows = grouped_rows("COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS name", "COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类')")
    applicant_rows = grouped_rows("COALESCE(NULLIF(TRIM(h.`申请人`), ''), '未设置') AS name", "COALESCE(NULLIF(TRIM(h.`申请人`), ''), '未设置')")

    applicant_product_rows = db.execute(
        text(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(d.`货品编号`), ''), '未设置') AS product_code,
              COALESCE(NULLIF(TRIM(d.`货品名称`), ''), '未设置') AS product,
              COALESCE(NULLIF(TRIM(d.`品牌`), ''), '未归类') AS brand,
              COALESCE(NULLIF(TRIM(d.`货品分类`), ''), '未归类') AS product_type,
              COUNT(DISTINCT h.`预留单ID`) AS order_count,
              COALESCE(SUM(d.`预留数量`), 0) AS reserved_quantity,
              COALESCE(SUM(d.`剩余数量`), 0) AS remaining_quantity,
              COALESCE(SUM(d.`已用数量`), 0) AS used_quantity,
              COALESCE(SUM(d.`已释放数量`), 0) AS released_quantity
            {joined_from}
            WHERE {where_sql}
            GROUP BY d.`货品编号`, d.`货品名称`, d.`品牌`, d.`货品分类`
            ORDER BY remaining_quantity DESC, reserved_quantity DESC
            """
        ),
        params,
    ).mappings().all()

    trend_rows = db.execute(
        text(
            f"""
            SELECT DATE_FORMAT(h.`申请时间`, '%Y-%m') AS month,
              COUNT(DISTINCT h.`预留单ID`) AS order_count,
              COALESCE(SUM(d.`预留数量`), 0) AS reserved_quantity,
              COALESCE(SUM(d.`剩余数量`), 0) AS remaining_quantity
            {joined_from}
            WHERE {where_sql} AND h.`申请时间` IS NOT NULL
            GROUP BY DATE_FORMAT(h.`申请时间`, '%Y-%m')
            ORDER BY month
            """
        ),
        params,
    ).mappings().all()

    expiry_rows = db.execute(
        text(
            f"""
            SELECT expiry_bucket AS name, COUNT(DISTINCT reserve_id) AS order_count,
                   COALESCE(SUM(remaining_quantity), 0) AS remaining_quantity
            FROM (
              SELECT h.`预留单ID` AS reserve_id, d.`剩余数量` AS remaining_quantity,
                CASE
                  WHEN h.`使用结束日期` IS NULL THEN '未设置使用结束日'
                  WHEN DATE(h.`使用结束日期`) < CURDATE() THEN '已过使用结束日'
                  WHEN DATE(h.`使用结束日期`) < CURDATE() + INTERVAL 8 DAY THEN '7日内到期'
                  WHEN DATE(h.`使用结束日期`) < CURDATE() + INTERVAL 31 DAY THEN '8-30日到期'
                  ELSE '31日后到期'
                END AS expiry_bucket
              {joined_from}
              WHERE {where_sql} AND d.`剩余数量` > 0
            ) scoped
            GROUP BY expiry_bucket
            ORDER BY FIELD(expiry_bucket, '已过使用结束日', '7日内到期', '8-30日到期', '31日后到期', '未设置使用结束日')
            """
        ),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"SELECT COUNT(*) {joined_from} WHERE {where_sql}"), params
    ).scalar_one()
    detail_params = {**params, "limit": page_size, "offset": (page - 1) * page_size}
    details = db.execute(
        text(
            f"""
            SELECT
              h.`预留单号` AS reservation_number, h.`状态` AS status,
              h.`预留仓库` AS warehouse, h.`申请部门` AS department, h.`申请人` AS applicant,
              h.`申请时间` AS application_time, h.`使用起始日期` AS start_time,
              h.`使用结束日期` AS end_time, h.`预留原因` AS reason,
              d.`货品编号` AS product_code, d.`货品名称` AS product,
              d.`品牌` AS brand, d.`货品分类` AS product_type,
              d.`条码` AS barcode, d.`单位` AS unit,
              d.`预留数量` AS reserved_quantity, d.`剩余数量` AS remaining_quantity,
              d.`已用数量` AS used_quantity, d.`已释放数量` AS released_quantity
            {joined_from}
            WHERE {where_sql}
            ORDER BY h.`申请时间` DESC, h.`预留单号` DESC, d.`明细ID` DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        detail_params,
    ).mappings().all()

    def serialize_group(rows: list[dict]) -> list[dict]:
        return [
            {
                "name": _label(row["name"]),
                "order_count": _integer(row["order_count"]),
                "reserved_quantity": _number(row["reserved_quantity"]),
                "remaining_quantity": _number(row["remaining_quantity"]),
                "retention_rate": _retention_rate(row["remaining_quantity"], row["reserved_quantity"]),
                "used_quantity": _number(row["used_quantity"]),
                "released_quantity": _number(row["released_quantity"]),
            }
            for row in rows
        ]

    response.headers["X-BI-Query-Mode"] = "ods-current-snapshot"
    response.headers["X-BI-Response-Source"] = "ods"
    return ok(
        {
            "scope": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
                "source_min_date": _date_text(coverage["min_date"]),
                "source_max_date": _date_text(coverage["max_date"]),
                "updated_at": _date_text(coverage["updated_at"]),
            },
            "filter_options": {
                "statuses": sorted({_label(row["status"]) for row in option_rows}),
                "warehouses": sorted({_label(row["warehouse"]) for row in option_rows}),
                "brands": sorted({_label(row["brand"], "未归类") for row in option_rows}),
                "product_types": sorted({_label(row["product_type"], "未归类") for row in option_rows}),
                "departments": sorted({_label(row["department"]) for row in option_rows}),
                "applicants": sorted({_label(row["applicant"]) for row in option_rows}),
            },
            "summary": {
                "order_count": _integer(summary["order_count"]),
                "active_order_count": _integer(summary["active_order_count"]),
                "sku_count": _integer(summary["sku_count"]),
                "reserved_quantity": _number(summary["reserved_quantity"]),
                "remaining_quantity": _number(summary["remaining_quantity"]),
                "used_quantity": _number(summary["used_quantity"]),
                "released_quantity": _number(summary["released_quantity"]),
            },
            "statuses": serialize_group(status_rows),
            "warehouses": serialize_group(warehouse_rows),
            "brands": serialize_group(brand_rows),
            "product_types": serialize_group(product_type_rows),
            "applicants": serialize_group(applicant_rows),
            "applicant_products": [
                {
                    "product_code": _label(row["product_code"], "-"),
                    "product": _label(row["product"], "-"),
                    "brand": _label(row["brand"], "未归类"),
                    "product_type": _label(row["product_type"], "未归类"),
                    "order_count": _integer(row["order_count"]),
                    "reserved_quantity": _number(row["reserved_quantity"]),
                    "remaining_quantity": _number(row["remaining_quantity"]),
                    "retention_rate": _retention_rate(row["remaining_quantity"], row["reserved_quantity"]),
                    "used_quantity": _number(row["used_quantity"]),
                    "released_quantity": _number(row["released_quantity"]),
                }
                for row in applicant_product_rows
            ],
            "trend": [
                {
                    "month": row["month"],
                    "order_count": _integer(row["order_count"]),
                    "reserved_quantity": _number(row["reserved_quantity"]),
                    "remaining_quantity": _number(row["remaining_quantity"]),
                }
                for row in trend_rows
            ],
            "expiry": [
                {
                    "name": _label(row["name"]),
                    "order_count": _integer(row["order_count"]),
                    "remaining_quantity": _number(row["remaining_quantity"]),
                }
                for row in expiry_rows
            ],
            "pagination": {"page": page, "page_size": page_size, "total": _integer(total)},
            "details": [
                {
                    "reservation_number": _label(row["reservation_number"], "-"),
                    "status": _label(row["status"]),
                    "warehouse": _label(row["warehouse"]),
                    "department": _label(row["department"]),
                    "applicant": _label(row["applicant"]),
                    "application_time": _date_text(row["application_time"]),
                    "start_time": _date_text(row["start_time"]),
                    "end_time": _date_text(row["end_time"]),
                    "reason": _label(row["reason"], "-"),
                    "product_code": _label(row["product_code"], "-"),
                    "product": _label(row["product"], "-"),
                    "brand": _label(row["brand"], "未归类"),
                    "product_type": _label(row["product_type"], "未归类"),
                    "barcode": _label(row["barcode"], "-"),
                    "unit": _label(row["unit"], "件"),
                    "reserved_quantity": _number(row["reserved_quantity"]),
                    "remaining_quantity": _number(row["remaining_quantity"]),
                    "used_quantity": _number(row["used_quantity"]),
                    "released_quantity": _number(row["released_quantity"]),
                }
                for row in details
            ],
        }
    )
