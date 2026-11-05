from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, permission_codes
from app.db.ads import get_ads_db
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.models.inventory_watch import InventoryWatch, InventoryWatchAudit
from app.models.user import User
from app.schemas.common import ok
from app.services import inventory_watch as source
from app.services.inventory_ads import InventoryAdsUnavailable


def watch_access(user: User = Depends(get_current_user)):
    if not permission_codes(user).intersection({"sales.view", "inventory.view"}):
        raise HTTPException(403, "需要销售或库存查看权限")
    return user


router = APIRouter(prefix="/inventory-watches", tags=["inventory-watches"], dependencies=[Depends(watch_access)])
Admin = Annotated[Session, Depends(get_db)]
ODS = Annotated[Session, Depends(get_ods_db)]
ADS = Annotated[Session, Depends(get_ads_db)]
Actor = Annotated[User, Depends(watch_access)]


class BatchAdd(BaseModel):
    channel_codes: list[str] = Field(min_length=1, max_length=50)
    product_codes: list[str] = Field(min_length=1, max_length=200)

    @field_validator("channel_codes", "product_codes")
    @classmethod
    def normalize(cls, values):
        if any(not v.strip() or len(v.strip()) > 128 for v in values):
            raise ValueError("编号不能为空且不能超过128个字符")
        return sorted(set(v.strip() for v in values))


class NoteUpdate(BaseModel):
    note: str = Field(max_length=1000)
    revision: int = Field(ge=1)


def catalog(ads, warehouses=(), codes=None):
    try:
        return source.inventory(ads, warehouses, codes)
    except InventoryAdsUnavailable as exc:
        raise HTTPException(503, "库存快照尚未就绪，请检查库存同步") from exc


@router.get("/options")
def options(db: Admin, ods: ODS, ads: ADS):
    stocks, scope = catalog(ads)
    channel_options = source.channels(ods)
    mapping = {c["code"]: c for c in channel_options}
    configured = [dict(code=code, name=mapping.get(code, {}).get("name") or name, product_count=count)
                  for code, name, count in db.execute(select(
                      InventoryWatch.channel_code, func.max(InventoryWatch.channel_name), func.count(InventoryWatch.id)
                  ).group_by(InventoryWatch.channel_code))]
    configured.sort(key=lambda c: (c["name"], c["code"]))
    return ok(dict(channels=channel_options, configured_channels=configured,
                   brands=sorted({r["brand"] for r in stocks.values() if r["brand"]}),
                   product_types=sorted({r["product_type"] for r in stocks.values() if r["product_type"]}),
                   warehouses=[r["warehouse"] for r in source.rows(ads, """SELECT DISTINCT warehouse
                     FROM ads_inventory_health_item WHERE data_version=:version ORDER BY warehouse""",
                     {"version": scope["inventory_version"]})]))


@router.get("/candidates")
def candidates(db: Admin, ods: ODS, ads: ADS,
               channel_code: list[str] = Query(default=[]), keyword: str = Query("", max_length=100),
               brand: str = "", product_type: list[str] = Query(default=[]), mode: str = Query("sales", pattern="^(sales|all)$"),
               sort: str = Query("quantity", pattern="^(quantity|amount|stock|available|product|product_code|brand|product_type)$"),
               direction: str = Query("descending", pattern="^(ascending|descending)$"),
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=10, le=100)):
    mapping = {r["code"]: r for r in source.channels(ods)}
    if set(channel_code) - mapping.keys():
        raise HTTPException(422, "渠道不存在，请刷新筛选项")
    stocks, scope = catalog(ads)
    sold, sales_scope = source.sales(ods, [mapping[c]["name"] for c in set(channel_code)])
    scope.update(sales_scope)
    data = {code: {**r, "quantity": 0., "amount": 0., "channel_sales": []} for code, r in stocks.items()}
    for s in sold:
        code = s["product_code"]
        row = data.setdefault(code, dict(product_code=code, product=s["product"], brand=s["brand"],
                                        product_type=s["product_type"], stock=None, available=None,
                                        quantity=0., amount=0., channel_sales=[]))
        row["quantity"] += float(s["quantity"] or 0)
        row["amount"] += float(s["amount"] or 0)
        row["channel_sales"].append(dict(channel=s["channel"], quantity=float(s["quantity"] or 0)))
    watched = {}
    for code, channel in db.execute(select(InventoryWatch.product_code, InventoryWatch.channel_code)):
        watched.setdefault(code, []).append(channel)
    sold_codes = {s["product_code"] for s in sold}
    product_types = {value.strip() for value in product_type if value.strip()}
    result = []
    for code, r in data.items():
        if mode == "sales" and code not in sold_codes:
            continue
        if brand and r.get("brand") != brand or product_types and r.get("product_type") not in product_types:
            continue
        if keyword.strip().casefold() not in (code + " " + (r.get("product") or "") + " " + (r.get("brand") or "")).casefold():
            continue
        result.append({**r, "watched_channels": watched.get(code, [])})
    result, pagination = source.page_rows(result, page, page_size, sort, direction == "descending")
    return ok(dict(rows=result, pagination=pagination, scope=scope))


@router.post("/batch")
def batch_add(body: BatchAdd, db: Admin, ods: ODS, ads: ADS, user: Actor):
    if len(body.channel_codes) * len(body.product_codes) > 1000:
        raise HTTPException(422, "每次最多添加1000个渠道货品组合")
    mapping = {r["code"]: r for r in source.channels(ods)}
    if set(body.channel_codes) - mapping.keys():
        raise HTTPException(422, "渠道不存在，请刷新后重试")
    # Validate codes against the same inventory + recent sales universe used by the picker.
    stocks, _ = catalog(ads, codes=body.product_codes)
    missing = sorted(set(body.product_codes) - stocks.keys())
    # Reference channels and target channels can differ. A valid sold SKU with
    # no stock must still be addable to a channel with no recent sales.
    sold, _ = source.sales(ods, sorted({c["name"] for c in mapping.values()}), missing) if missing else ([], {})
    products = {r["product_code"]: r for r in sold}
    products.update(stocks)
    if set(body.product_codes) - products.keys():
        raise HTTPException(422, "部分货品已不在当前数据中，请刷新候选列表")
    added = 0
    for channel in body.channel_codes:
        for code in body.product_codes:
            values = dict(channel_code=channel, channel_name=mapping[channel]["name"],
                          product_code=code, product_name=products[code]["product"] or code,
                          created_by=user.id, updated_by=user.id)
            if db.get_bind().dialect.name == "sqlite":
                # Use a real outer DML transaction: releasing the first SAVEPOINT in
                # SQLite's legacy transaction mode would otherwise commit early.
                inserted = db.execute(sqlite_insert(InventoryWatch).values(**values).on_conflict_do_nothing(
                    index_elements=["channel_code", "product_code"])).rowcount == 1
                if inserted:
                    db.add(InventoryWatchAudit(channel_code=channel, product_code=code, action="add", actor_id=user.id))
                    added += 1
                continue
            try:
                with db.begin_nested():
                    db.add(InventoryWatch(**values))
                    db.flush()
                    db.add(InventoryWatchAudit(channel_code=channel, product_code=code, action="add", actor_id=user.id))
                added += 1
            except IntegrityError:
                # The unique key resolves both repeated submissions and concurrent additions.
                existing = db.scalar(select(InventoryWatch.id).where(InventoryWatch.channel_code == channel,
                                                                    InventoryWatch.product_code == code))
                if existing is None:
                    raise
    db.commit()
    return ok(dict(added=added, existing=len(body.channel_codes) * len(body.product_codes) - added))


@router.patch("/{watch_id}")
def update_note(watch_id: int, body: NoteUpdate, db: Admin, user: Actor):
    row = db.get(InventoryWatch, watch_id)
    if row is None:
        raise HTTPException(404, "关注配置已不存在")
    result = db.execute(update(InventoryWatch).where(InventoryWatch.id == watch_id,
                        InventoryWatch.revision == body.revision).values(note=body.note.strip(),
                        revision=body.revision + 1, updated_by=user.id, updated_at=datetime.utcnow()))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "备注已被其他账号修改，请刷新后重试")
    db.add(InventoryWatchAudit(channel_code=row.channel_code, product_code=row.product_code,
                               action="note", note=body.note.strip(), actor_id=user.id))
    db.commit()
    return ok(dict(revision=body.revision + 1))


@router.delete("/{watch_id}")
def remove(watch_id: int, db: Admin, user: Actor):
    row = db.get(InventoryWatch, watch_id)
    if row:
        db.add(InventoryWatchAudit(channel_code=row.channel_code, product_code=row.product_code,
                                   action="delete", note=row.note, actor_id=user.id))
        db.execute(delete(InventoryWatch).where(InventoryWatch.id == watch_id))
        db.commit()
    return ok()


@router.get("")
def listing(db: Admin, ods: ODS, ads: ADS, channel_code: list[str] = Query(default=[]),
            warehouse: list[str] = Query(default=[]), brand: str = "", product_type: list[str] = Query(default=[]),
            keyword: str = Query("", max_length=100), view: str = Query("product", pattern="^(product|channel)$"),
            status: str = Query("all", pattern="^(all|reserved|expiring|overdue|manual|automatic)$"),
            sort: str = Query("remaining", pattern="^(quantity|stock|available|remaining|my_remaining|end_time|product|product_code|brand|product_type|channel_name|rules)$"),
            direction: str = Query("descending", pattern="^(ascending|descending)$"),
            page: int = Query(1, ge=1), page_size: int = Query(20, ge=10, le=100)):
    statement = select(InventoryWatch).order_by(InventoryWatch.id)
    if channel_code:
        statement = statement.where(InventoryWatch.channel_code.in_(channel_code))
    watches = db.scalars(statement).all()
    codes = sorted({w.product_code for w in watches})
    stocks, scope = catalog(ads, warehouse, codes)
    mapping = {r["code"]: r for r in source.channels(ods)}
    names = sorted({mapping[w.channel_code]["name"] for w in watches if w.channel_code in mapping})
    sold, sales_scope = source.sales(ods, names, codes)
    reserved, coverage = source.reservations(ods, codes, warehouse)
    scope.update(sales_scope)
    scope.update(coverage)
    channel_reserved = source.channel_reservations(ods, codes, warehouse)
    data = source.assemble(watches, stocks, sold, reserved, mapping, view, channel_reserved)
    filtered = []
    for r in data:
        if brand and r["brand"] != brand or product_type and r["product_type"] not in product_type:
            continue
        if keyword.strip().casefold() not in (r["product_code"] + " " + r["product"]).casefold():
            continue
        if status == "reserved" and r["remaining"] <= 0:
            continue
        if status == "expiring" and not r["expiring_count"]:
            continue
        if status == "overdue" and not r["overdue_count"]:
            continue
        if status == "manual" and "手工释放" not in r["rules"]:
            continue
        if status == "automatic" and "到期自动释放" not in r["rules"]:
            continue
        filtered.append(r)
    unique = {r["product_code"]: r for r in filtered}
    summary = dict(products=len(unique), relations=sum(len(r["relations"]) for r in filtered),
                   reserved_products=sum(r["remaining"] > 0 for r in unique.values()),
                   expiring_products=sum(r["expiring_count"] > 0 for r in unique.values()))
    data, pagination = source.page_rows(filtered, page, page_size, sort, direction == "descending")
    return ok(dict(rows=data, summary=summary, pagination=pagination, scope=scope))


@router.get("/products/{product_code}")
def product_detail(product_code: str, ods: ODS, ads: ADS, warehouse: list[str] = Query(default=[]),
                   channel_code: str | None = None, mine_only: bool = False,
                   sort: str = Query("priority", pattern="^(priority|number|status|warehouse|object_name|applied_at|start_time|end_time|rule|reserved|remaining|used|released)$"),
                   direction: str = Query("ascending", pattern="^(ascending|descending)$"),
                   page: int = Query(1, ge=1), page_size: int = Query(20, ge=10, le=100)):
    _, scope = catalog(ads, warehouse, [product_code])
    lists = {"warehouses": warehouse} if warehouse else {}
    stock_where = " AND warehouse IN :warehouses" if warehouse else ""
    stocks = source.rows(ads, f"""SELECT warehouse, SUM(stock) AS stock, SUM(available_stock) AS available
        FROM ads_inventory_health_item
        WHERE data_version=:version AND product_code=:code {stock_where}
        GROUP BY warehouse HAVING SUM(stock) > 0 ORDER BY available DESC, warehouse""",
        {"version": scope["inventory_version"], "code": product_code}, **lists)
    _, reservation_scope = source.reservations(ods, [product_code], warehouse)
    scope.update(reservation_scope)
    reservation_where = " AND h.`预留仓库` IN :warehouses" if warehouse else ""
    detail_params = {"code": product_code}
    if mine_only:
        channel = next((c for c in source.channels(ods) if c["code"] == channel_code), None)
        if not channel or not channel.get("channel_id"):
            raise HTTPException(422, "当前渠道缺少预留对象ID，无法查看我的预留")
        detail_params["channel_id"] = str(channel["channel_id"])
        reservation_where += " AND h.`对象类型`='渠道' AND FIND_IN_SET(:channel_id, REPLACE(REPLACE(COALESCE(h.`预留对象ID`, ''), ' ', ''), '，', ',')) > 0"
    joined = f"""FROM `预留单货品明细` d JOIN `预留单查询` h ON h.`预留单ID`=d.`预留单ID`
        WHERE d.`货品编号`=:code AND h.`状态`='执行中' AND d.`剩余数量` > 0 {reservation_where}"""
    count = source.rows(ods, f"SELECT COUNT(*) AS n {joined}", detail_params, **lists)[0]["n"]
    columns = dict(number="h.`预留单号`", status="h.`状态`", warehouse="h.`预留仓库`", object_name="h.`预留对象`",
                   applied_at="h.`申请时间`", start_time="h.`使用起始日期`", end_time="h.`使用结束日期`",
                   rule="h.`到期释放`", reserved="d.`预留数量`", remaining="d.`剩余数量`",
                   used="d.`已用数量`", released="d.`已释放数量`")
    order = (f"{columns[sort]} {'DESC' if direction == 'descending' else 'ASC'}, " if sort != "priority" else
             "CASE WHEN h.`状态`='执行中' AND d.`剩余数量`>0 THEN 0 ELSE 1 END, h.`使用结束日期`, ")
    details = source.rows(ods, f"""SELECT h.`预留单号` AS number, h.`状态` AS status,
        h.`预留对象` AS object_name, h.`预留仓库` AS warehouse, h.`申请时间` AS applied_at,
        h.`使用起始日期` AS start_time, h.`使用结束日期` AS end_time,
        COALESCE(NULLIF(h.`到期释放`, ''), '未知') AS rule,
        d.`预留数量` AS reserved, d.`剩余数量` AS remaining, d.`已用数量` AS used,
        d.`已释放数量` AS released {joined}
        ORDER BY {order} h.`预留单ID`, d.`明细ID` LIMIT :limit OFFSET :offset""",
        {**detail_params, "limit": page_size, "offset": (page - 1) * page_size}, **lists)
    return ok(dict(stocks=stocks, reservations=details, pagination=dict(page=page, page_size=page_size, total=count), scope=scope))
