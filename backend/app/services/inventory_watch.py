"""Shared channel watches. ODS/DWD/ADS access is strictly read-only."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from app.services.inventory_ads import latest_ready_inventory_batch
from app.services.reservation_cache import cached


def recent_30_days(today=None):
    today = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    end = today - timedelta(days=1)
    return end - timedelta(days=29), end


def rows(db, sql, params=None, **lists):
    statement = text(sql)
    for key in lists:
        statement = statement.bindparams(bindparam(key, expanding=True))
    return [dict(row) for row in db.execute(statement, {**(params or {}), **lists}).mappings()]


def channels(ods):
    return rows(ods, """
        SELECT TRIM(`渠道编号`) AS code, MAX(`渠道名称`) AS name,
          MAX(CAST(`渠道ID` AS CHAR)) AS channel_id,
          CASE WHEN MAX(CASE WHEN NULLIF(TRIM(`线上平台`), '') IS NOT NULL
            AND TRIM(`线上平台`) NOT IN ('未设置', '-1', '0') THEN 1 ELSE 0 END) = 1
          THEN '线上' ELSE '线下' END AS kind
        FROM `渠道列表` WHERE NULLIF(TRIM(`渠道编号`), '') IS NOT NULL
        GROUP BY TRIM(`渠道编号`) ORDER BY name, code
    """)


def inventory(ads, warehouses=(), codes=None):
    batch = latest_ready_inventory_batch(ads)
    where = ["data_version=:version", "NULLIF(TRIM(product_code), '') IS NOT NULL"]
    lists = {}
    stock_expression = "stock"
    available_expression = "available_stock"
    if warehouses:
        lists["warehouses"] = warehouses
        stock_expression = "CASE WHEN warehouse IN :warehouses THEN stock END"
        available_expression = "CASE WHEN warehouse IN :warehouses THEN available_stock END"
    if codes is not None:
        where.append("product_code IN :codes")
        lists["codes"] = codes
    data = rows(ads, f"""
        SELECT product_code, MAX(product) AS product, MAX(brand) AS brand,
          MAX(product_type) AS product_type, SUM({stock_expression}) AS stock,
          SUM({available_expression}) AS available
        FROM ads_inventory_health_item WHERE {' AND '.join(where)}
        GROUP BY product_code
    """, {"version": batch.data_version}, **lists)
    scope = rows(ads, """SELECT MAX(updated_at) AS updated_at FROM ads_inventory_product_warehouse
        WHERE data_version=:version""", {"version": batch.data_version})[0]
    for row in data:
        row["updated_at"] = scope["updated_at"]
        if row["product_type"] in (None, "", "-1"):
            row["product_type"] = "未归类"
    return {r["product_code"]: r for r in data}, {
        "inventory_version": batch.data_version, "inventory_updated_at": scope["updated_at"],
    }


def sales(ods, channel_names, codes=None):
    start, end = recent_30_days()
    if not channel_names:
        return [], {"sales_start": start, "sales_end": end, "sales_source": "DWD渠道销售明细"}
    filters = ["`下单时间` >= :start", "`下单时间` < :end", "`销售渠道` IN :channels",
               "NULLIF(TRIM(`货品编号`), '') IS NOT NULL"]
    lists = {"channels": channel_names}
    if codes is not None:
        filters.append("`货品编号` IN :codes")
        lists["codes"] = codes
    sql = f"""
        SELECT `销售渠道` AS channel, `货品编号` AS product_code,
          MAX(`货品名称`) AS product, MAX(`品牌`) AS brand,
          MAX(CASE WHEN NULLIF(TRIM(`货品分类`), '') IS NULL OR TRIM(`货品分类`)='-1'
            THEN '未归类' ELSE TRIM(`货品分类`) END) AS product_type,
          SUM(COALESCE(`数量`, 0)) AS quantity, SUM(COALESCE(`分摊后金额`, 0)) AS amount,
          MAX(`updatetime`) AS updated_at
        FROM `dwd`.`销售单明细账_品牌补全` WHERE {' AND '.join(filters)}
        GROUP BY `销售渠道`, `货品编号`
    """
    cache_key = ("inventory-watch-sales-30d-v2", ods.get_bind(), start, end,
                 tuple(sorted(set(channel_names))), None if codes is None else tuple(sorted(set(codes))))
    data = cached(cache_key, lambda: rows(ods, sql, {"start": start, "end": end + timedelta(days=1)}, **lists))
    updated = max((r["updated_at"] for r in data if r["updated_at"]), default=None)
    return data, {"sales_start": start, "sales_end": end, "sales_updated_at": updated,
                  "sales_source": "DWD渠道销售明细（含负数，不等同于已发货量）"}


def reservations(ods, codes, warehouses=()):
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    lists = {"codes": codes}
    warehouse_sql = ""
    if warehouses:
        warehouse_sql = " AND h.`预留仓库` IN :warehouses"
        lists["warehouses"] = warehouses
    data = rows(ods, f"""
        SELECT d.`货品编号` AS product_code,
          SUM(d.`剩余数量`) AS remaining,
          MIN(h.`使用结束日期`) AS end_time,
          SUM(CASE WHEN h.`使用结束日期` >= :now AND h.`使用结束日期` <= :soon THEN 1 ELSE 0 END) AS expiring_count,
          SUM(CASE WHEN h.`使用结束日期` < :now THEN 1 ELSE 0 END) AS overdue_count,
          GROUP_CONCAT(DISTINCT COALESCE(NULLIF(h.`到期释放`, ''), '未知') SEPARATOR '、') AS rules,
          COUNT(DISTINCT h.`预留单ID`) AS order_count
        FROM `预留单货品明细` d JOIN `预留单查询` h ON h.`预留单ID`=d.`预留单ID`
        WHERE d.`货品编号` IN :codes AND h.`状态`='执行中' AND d.`剩余数量` > 0
          {warehouse_sql} GROUP BY d.`货品编号`
    """, {"now": now, "soon": now + timedelta(days=3)}, **lists)
    coverage = rows(ods, """SELECT
        (SELECT MAX(`updatetime`) FROM `预留单查询`) AS header_updated_at,
        (SELECT MAX(`updatetime`) FROM `预留单货品明细`) AS detail_updated_at""")[0]
    return {r["product_code"]: r for r in data}, coverage


def page_rows(data, page, page_size, sort, descending):
    # Stable secondary key makes ties deterministic across pages.
    data.sort(key=lambda r: (r["product_code"], r.get("channel_name", "")))
    known = [r for r in data if r.get(sort) is not None]
    missing = [r for r in data if r.get(sort) is None]
    known.sort(key=lambda r: r[sort], reverse=descending)
    data = known + missing
    return data[(page - 1) * page_size:page * page_size], {"page": page, "page_size": page_size, "total": len(data)}


def channel_reservations(ods, codes, warehouses=()):
    lists = {"codes": codes}
    warehouse_sql = ""
    if warehouses:
        warehouse_sql = " AND h.`预留仓库` IN :warehouses"
        lists["warehouses"] = warehouses
    return rows(ods, f"""SELECT d.`货品编号` AS product_code, h.`预留对象ID` AS object_ids,
        d.`剩余数量` AS remaining FROM `预留单货品明细` d
        JOIN `预留单查询` h ON h.`预留单ID`=d.`预留单ID`
        WHERE d.`货品编号` IN :codes AND h.`状态`='执行中'
          AND h.`对象类型`='渠道' AND d.`剩余数量`>0 {warehouse_sql}""", **lists)


def mine_quantity(records, channel_ids):
    """A shared reservation is counted once even if several selected channels match."""
    return sum(float(r["remaining"]) for r in records
               if channel_ids.intersection(token.strip() for token in str(r["object_ids"] or "").replace('，', ',').split(',')))


def assemble(watches, stocks, sold, reserved, channel_map, view, channel_reserved=()):
    sales_map = {(r["channel"], r["product_code"]): r for r in sold}
    groups = {}
    for watch in watches:
        key = (watch.product_code, watch.channel_code) if view == "channel" else watch.product_code
        groups.setdefault(key, []).append(watch)
    result = []
    for group in groups.values():
        code = group[0].product_code
        stock = stocks.get(code, {})
        metadata = stock or next((r for r in sold if r["product_code"] == code), {})
        reserve = reserved.get(code, {})
        relations = []
        channel_ids = {str(channel_map[w.channel_code]["channel_id"]) for w in group
                       if channel_map.get(w.channel_code, {}).get("channel_id")}
        for w in group:
            channel = channel_map.get(w.channel_code)
            name = channel["name"] if channel else w.channel_name
            sale = sales_map.get((name, code), {})
            relations.append(dict(id=w.id, channel_code=w.channel_code, channel_name=name,
                                  channel_missing=channel is None, quantity=float(sale.get("quantity") or 0),
                                  note=w.note, revision=w.revision))
        result.append(dict(product_code=code, product=metadata.get("product") or group[0].product_name,
                           brand=metadata.get("brand") or "未归类", product_type=metadata.get("product_type") or "未归类",
                           stock=float(stock["stock"]) if stock.get("stock") is not None else None,
                           available=float(stock["available"]) if stock.get("available") is not None else None,
                           remaining=float(reserve.get("remaining") or 0),
                           my_remaining=mine_quantity([r for r in channel_reserved if r["product_code"] == code], channel_ids) if channel_ids else None,
                           end_time=reserve.get("end_time"), rules=reserve.get("rules") or "无有效预留",
                           expiring_count=int(reserve.get("expiring_count") or 0),
                           overdue_count=int(reserve.get("overdue_count") or 0),
                           order_count=int(reserve.get("order_count") or 0), relations=relations,
                           channel_name=relations[0]["channel_name"] if view == "channel" else "",
                           quantity=sum(r["quantity"] for r in relations)))
    return result
