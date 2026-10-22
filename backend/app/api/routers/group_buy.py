from copy import deepcopy
from hashlib import sha256
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.db.session import get_db
from app.db.ods import get_ods_db
from app.models.group_buy import GroupBuyBatch, GroupBuyChange
from app.schemas.common import ok
from app.schemas.group_buy import BRANDS, AddColumn, AddQuota, CreateBatch, ProductInput, RenameBatch, RenameLabel, RevisionInput, SaveCells
from app.services import group_buy as service


router = APIRouter(prefix="/group-buy", tags=["group-buy"])
manage = require_permission("group_buy.manage")


@router.get("/catalog")
def catalog(code: str = Query(min_length=1, max_length=128), user=Depends(manage), ods: Session = Depends(get_ods_db)):
    try:
        return ok(service.lookup_product(ods, code))
    except SQLAlchemyError:
        service.fail("商品库查询暂不可用，请稍后重试", 503)


@router.get("/batches")
def batches(month: str = "", brand: str = "", deleted: bool = False, db: Session = Depends(get_db), user=Depends(manage)):
    query = db.query(GroupBuyBatch).filter(GroupBuyBatch.status == "deleted" if deleted else GroupBuyBatch.status != "deleted")
    if month:
        query = query.filter(GroupBuyBatch.month == month)
    if brand:
        query = query.filter(GroupBuyBatch.brand == brand)
    return ok({"brands": BRANDS, "rows": [service.batch_data(b) for b in query.order_by(GroupBuyBatch.month.desc(), GroupBuyBatch.id.desc()).limit(500).all()]})


@router.post("/batches")
def create_batch(body: CreateBatch, db: Session = Depends(get_db), user=Depends(manage)):
    name = body.name.strip()
    if not name:
        service.fail("批次名称不能为空")
    doc = service.empty_document()
    if body.copy_from:
        original = service.get_batch(db, body.copy_from)
        if original.brand != body.brand:
            service.fail("仅支持复制同品牌批次")
        doc = deepcopy(original.document)
        for p in doc["products"]:
            p["orders"], p["allocations"] = {}, {}
            p["quotas"] = {s["id"]: 0 for s in doc["sources"]}
    batch = GroupBuyBatch(month=body.month, brand=body.brand, name=name, document=doc, created_by=user.username)
    db.add(batch)
    try:
        db.flush()
        db.add(GroupBuyChange(batch_id=batch.id, revision=1, action="create",
                              changes={"message": "建立批次（复制时清空数量，价格保留待业务核对）", "copy_from": body.copy_from}, operator=user.username))
        db.commit()
    except IntegrityError:
        db.rollback()
        service.fail("同月份、品牌下已存在同名批次（包括回收站），请改名或恢复旧批次", 409)
    return ok(service.batch_data(batch))


@router.patch("/batches/{batch_id}")
def rename_batch(batch_id: int, body: RenameBatch, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision, editable=False)
    try:
        result = service.save_document(db, batch, body.revision, batch.document, "rename",
                                       {"before": batch.name, "after": body.name}, user.username, name=body.name)
    except IntegrityError:
        db.rollback()
        service.fail("同月份、品牌下已存在同名批次（包括回收站），请使用其他名称", 409)
    return ok(service.batch_data(result))


@router.delete("/batches/{batch_id}")
def delete_batch(batch_id: int, body: RevisionInput, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision, editable=False)
    result = service.save_document(db, batch, body.revision, batch.document, "delete",
                                   {"before": batch.status, "after": "deleted", "message": "批次移入回收站，数据和历史保留"},
                                   user.username, status="deleted")
    return ok(service.batch_data(result))


@router.post("/batches/{batch_id}/restore")
def restore_batch(batch_id: int, body: RevisionInput, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id, include_deleted=True)
    service.check_revision(batch, body.revision, editable=False)
    if batch.status != "deleted":
        service.fail("此批次未删除，无需恢复", 409)
    deletion = db.query(GroupBuyChange).filter(GroupBuyChange.batch_id == batch_id, GroupBuyChange.action == "delete").order_by(GroupBuyChange.revision.desc()).first()
    previous = deletion.changes.get("before", "draft") if deletion else "draft"
    status = previous if previous in ("draft", "confirmed") else "draft"
    result = service.save_document(db, batch, body.revision, batch.document, "restore",
                                   {"before": "deleted", "after": status, "message": "从回收站恢复批次"}, user.username, status=status)
    return ok(service.batch_data(result))


@router.get("/batches/{batch_id}")
def table(batch_id: int, keyword: str = "", source: str = "", customer: str = "",
          only_os: bool = False, only_gap: bool = False,
          sort_by: str = Query("position", pattern="^(position|code|name|barcode|price|abc|pcb|quota|allocated|remaining|ordered)$"),
          sort_order: str = Query("asc", pattern="^(asc|desc)$"),
          page: int = Query(1, ge=1), page_size: int = Query(30, ge=10, le=100), all_rows: bool = False,
          db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    doc = batch.document
    columns = [c for c in doc["columns"] if (not source or c["source_id"] == source) and (not customer or c["customer"] == customer)]
    items = []
    for p in doc["products"]:
        if keyword and keyword.lower() not in f'{p["code"]} {p["name"]} {p["barcode"]}'.lower():
            continue
        if only_os and p["abc"] != "OS":
            continue
        t = service.totals(doc, p)
        if only_gap and not (t["remaining"] or t["missing_sources"] or t["over_sources"]):
            continue
        items.append({**p, "totals": t})
    filtered_summary = service.summary({**doc, "products": items})
    if sort_by != "position":
        def key(p):
            value = p.get(sort_by) if sort_by in p else p["totals"].get(sort_by)
            if sort_by == "price":
                value = float(value)
            return (value is None, value if value is not None else 0)
        items.sort(key=key, reverse=sort_order == "desc")
    # The editable matrix requests the complete bounded batch. Keep pagination
    # available for product selectors and other API clients.
    rows = items if all_rows else items[(page - 1) * page_size:page * page_size]
    return ok({"batch": service.batch_data(batch), "sources": doc["sources"], "columns": columns,
               "all_columns": doc["columns"], "customers": sorted({c["customer"] for c in doc["columns"]}),
               "summary": filtered_summary,
               "pagination": {"page": 1 if all_rows else page, "page_size": len(items) if all_rows else page_size,
                              "total": len(items)}, "rows": rows})


@router.patch("/batches/{batch_id}/cells")
def save_cells(batch_id: int, body: SaveCells, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    changes = service.change_cells(doc, body.cells)
    result = service.save_document(db, batch, body.revision, doc, "cells", {"cells": changes}, user.username)
    return ok(service.batch_data(result))


@router.post("/batches/{batch_id}/columns")
def add_column(batch_id: int, body: AddColumn, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    if not body.customer and not body.counter:
        service.fail("请填写客户名称，或勾选下单柜台")
    source = service.ensure_source(doc, body.source, body.counter)
    if any(c["source_id"] == source["id"] and c["customer"] == body.customer for c in doc["columns"]):
        service.fail("该来源下客户列已存在")
    if body.customer:
        doc["columns"].append({"id": service.uid(), "source_id": source["id"], "customer": body.customer,
                               "origin": "在线新增", "position": len(doc["columns"])})
    result = service.save_document(db, batch, body.revision, doc, "column", body.model_dump(exclude={"revision"}), user.username)
    return ok(service.batch_data(result))


@router.patch("/batches/{batch_id}/columns/{column_id}")
def rename_column(batch_id: int, column_id: str, body: RenameLabel, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    column = next((c for c in doc["columns"] if c["id"] == column_id), None)
    if column is None:
        service.fail("客户列不存在", 404)
    if body.name != column["customer"] and any(c["id"] != column_id and c["source_id"] == column["source_id"] and c["customer"] == body.name for c in doc["columns"]):
        service.fail("该来源下已有同名客户列")
    before = deepcopy(column)
    column["customer"] = body.name
    result = service.save_document(db, batch, body.revision, doc, "column_update", {"before": before, "after": deepcopy(column)}, user.username)
    return ok(service.batch_data(result))


@router.patch("/batches/{batch_id}/sources/{source_id}")
def rename_source(batch_id: int, source_id: str, body: RenameLabel, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    source = next((s for s in doc["sources"] if s["id"] == source_id), None)
    if source is None:
        service.fail("来源不存在", 404)
    if any(s["id"] != source_id and s["name"] == body.name for s in doc["sources"]):
        service.fail("来源名称已存在")
    before = deepcopy(source)
    source["name"] = body.name
    result = service.save_document(db, batch, body.revision, doc, "source_update", {"before": before, "after": deepcopy(source)}, user.username)
    return ok(service.batch_data(result))


@router.delete("/batches/{batch_id}/{collection}/{item_id}")
def delete_item(batch_id: int, collection: str, item_id: str, body: RevisionInput, db: Session = Depends(get_db), user=Depends(manage)):
    if collection not in ("products", "columns", "sources"):
        service.fail("操作不存在", 404)
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    changes = service.remove_item(doc, collection, item_id)
    result = service.save_document(db, batch, body.revision, doc, f"{collection}_delete", changes, user.username)
    return ok(service.batch_data(result))


@router.post("/batches/{batch_id}/quotas")
def add_quota(batch_id: int, body: AddQuota, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    p = service.find_product(doc, body.product_id)
    source = service.ensure_source(doc, body.source)
    before = p["quotas"].get(source["id"])
    if before is None and body.mode == "add":
        service.fail("当前额度未知，请先用“设置总额度”明确可分配数量")
    p["quotas"][source["id"]] = body.quantity if body.mode == "set" else before + body.quantity
    if p["quotas"][source["id"]] > 100_000_000:
        service.fail("分配额度过大")
    changes = {**body.model_dump(exclude={"revision"}), "code": p["code"], "before": before, "after": p["quotas"][source["id"]]}
    result = service.save_document(db, batch, body.revision, doc, "quota", changes, user.username)
    return ok(service.batch_data(result))


@router.post("/batches/{batch_id}/products")
def add_product(batch_id: int, body: ProductInput, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    if any(p["code"] == body.code for p in doc["products"]):
        service.fail("产品代码已存在")
    item = body.model_dump(mode="json", exclude={"revision"})
    item.update(id=service.uid(), orders={}, allocations={}, quotas={s["id"]: 0 for s in doc["sources"]})
    doc["products"].append(item)
    result = service.save_document(db, batch, body.revision, doc, "product", {"code": body.code, "name": body.name}, user.username)
    return ok(service.batch_data(result))


@router.patch("/batches/{batch_id}/products/{product_id}")
def update_product(batch_id: int, product_id: str, body: ProductInput, db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision)
    doc = deepcopy(batch.document)
    p = service.find_product(doc, product_id)
    if any(x["id"] != product_id and x["code"] == body.code for x in doc["products"]):
        service.fail("产品代码已存在")
    values = body.model_dump(mode="json", exclude={"revision"})
    before = {k: p.get(k) for k in values}
    p.update(values)
    result = service.save_document(db, batch, body.revision, doc, "product_update",
                                   {"code": body.code, "before": before, "after": values}, user.username)
    return ok(service.batch_data(result))


@router.post("/batches/{batch_id}/{action}")
def change_status(batch_id: int, action: str, body: RevisionInput, db: Session = Depends(get_db), user=Depends(manage)):
    if action not in ("confirm", "reopen"):
        service.fail("操作不存在", 404)
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, body.revision, editable=False)
    if action == "confirm":
        if not batch.document["products"]:
            service.fail("空批次不能确认")
        s = service.summary(batch.document)
        if s["missing_count"] or s["over_count"]:
            service.fail(f"有{s['missing_count']}件商品额度待维护、{s['over_count']}件商品来源超配，请先处理")
    result = service.save_document(db, batch, body.revision, batch.document, action,
                                   {"before": batch.status, "after": "confirmed" if action == "confirm" else "draft"},
                                   user.username, status="confirmed" if action == "confirm" else "draft")
    return ok(service.batch_data(result))


async def read_import(order_file, allocation_file):
    if not order_file and not allocation_file:
        service.fail("至少选择下单表或分配表")
    parsed, files = {}, []
    for kind, upload in (("order", order_file), ("allocation", allocation_file)):
        if upload:
            content = await upload.read(12 * 1024 * 1024 + 1)
            parsed[kind] = service.parse_workbook(content, kind)
            files.append({"kind": kind, "name": (upload.filename or "")[:255], "sha256": sha256(content).hexdigest()})
    return parsed, files


@router.post("/batches/{batch_id}/import/preview")
async def import_preview(batch_id: int, revision: int = Form(...), order_file: UploadFile | None = File(None),
                         allocation_file: UploadFile | None = File(None), db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, revision)
    parsed, files = await read_import(order_file, allocation_file)
    doc = service.merge_import(batch.document, **parsed)
    return ok({"files": files, "summary": service.summary(doc), "sources": doc["sources"],
               "product_count": len(doc["products"]), "column_count": len(doc["columns"]),
               "duplicate_columns": len(doc["columns"]) - len({(c["source_id"], c["customer"]) for c in doc["columns"]})})


@router.post("/batches/{batch_id}/import/apply")
async def import_apply(batch_id: int, revision: int = Form(...), order_file: UploadFile | None = File(None),
                       allocation_file: UploadFile | None = File(None), db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    service.check_revision(batch, revision)
    parsed, files = await read_import(order_file, allocation_file)
    doc = service.merge_import(batch.document, **parsed)
    result = service.save_document(db, batch, revision, doc, "import", {"files": files, "summary": service.summary(doc)}, user.username)
    return ok(service.batch_data(result))


@router.get("/batches/{batch_id}/history")
def history(batch_id: int, page: int = Query(1, ge=1), db: Session = Depends(get_db), user=Depends(manage)):
    service.get_batch(db, batch_id, include_deleted=True)
    query = db.query(GroupBuyChange).filter(GroupBuyChange.batch_id == batch_id)
    return ok({"total": query.count(), "rows": [{"id": r.id, "revision": r.revision, "action": r.action,
        "changes": r.changes, "operator": r.operator, "created_at": r.created_at.isoformat()}
        for r in query.order_by(GroupBuyChange.revision.desc()).offset((page - 1) * 20).limit(20).all()]})


@router.get("/batches/{batch_id}/export")
def export(batch_id: int, kind: str = Query("allocation", pattern="^(order|allocation)$"),
           db: Session = Depends(get_db), user=Depends(manage)):
    batch = service.get_batch(db, batch_id)
    data = service.export_workbook(batch.document, kind)
    name = quote(f"{batch.month} {batch.brand} {batch.name} - {'下单' if kind == 'order' else '分配'} v{batch.revision}.xlsx")
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
