from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from openpyxl import load_workbook
import xlsxwriter
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.models.core_cost_price import CoreCostPriceRevision
from app.models.user import User
from app.schemas.common import ok


router = APIRouter(prefix="/inventory/valuation", tags=["inventory-valuation"])


class PriceInput(BaseModel):
    product_code: str = Field(min_length=1, max_length=128)
    product_name: str = Field(default="", max_length=255)
    price: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    effective_date: date


class ImportInput(BaseModel):
    rows: list[PriceInput] = Field(min_length=1, max_length=5000)


def price_states(db: Session) -> tuple[dict[str, CoreCostPriceRevision], dict[str, CoreCostPriceRevision]]:
    revisions = db.query(CoreCostPriceRevision).filter(
        CoreCostPriceRevision.effective_date <= date.today()
    ).order_by(
        CoreCostPriceRevision.product_code,
        CoreCostPriceRevision.effective_date.desc(),
        CoreCostPriceRevision.id.desc(),
    ).all()
    deleted_ids = {}
    deleted = {}
    for revision in revisions:
        if revision.source == "delete" and revision.id > deleted_ids.get(revision.product_code, 0):
            deleted_ids[revision.product_code] = revision.id
            deleted[revision.product_code] = revision
    active = {}
    for revision in revisions:
        if revision.source != "delete" and revision.id > deleted_ids.get(revision.product_code, 0):
            active.setdefault(revision.product_code, revision)
    return active, {code: revision for code, revision in deleted.items() if code not in active}


def current_prices(db: Session) -> dict[str, CoreCostPriceRevision]:
    return price_states(db)[0]


def price_data(revision: CoreCostPriceRevision) -> dict:
    return {
        "id": revision.id,
        "product_code": revision.product_code,
        "product_name": revision.product_name,
        "price": float(revision.price),
        "effective_date": revision.effective_date.isoformat(),
        "source": revision.source,
        "restored_from_id": revision.restored_from_id,
        "operator": revision.operator,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
    }


def price_brands(ods: Session, codes: list[str]) -> dict[str, str]:
    brands = {}
    for start in range(0, len(codes), 500):
        batch = codes[start:start + 500]
        params = {f"code_{index}": code for index, code in enumerate(batch)}
        placeholders = ", ".join(f":{key}" for key in params)
        rows = ods.execute(text(f"""
            SELECT `货品编号` AS product_code, MAX(`品牌`) AS brand
            FROM `总库存查询` WHERE `货品编号` IN ({placeholders})
            GROUP BY `货品编号`
        """), params).mappings().all()
        brands.update({str(row["product_code"]): row["brand"] or "" for row in rows})
    return brands


def add_revision(db: Session, item: PriceInput, operator: str, source: str, restored_from_id: int | None = None) -> None:
    db.add(CoreCostPriceRevision(
        product_code=item.product_code.strip(), product_name=item.product_name.strip(),
        price=item.price, effective_date=item.effective_date, source=source,
        restored_from_id=restored_from_id, operator=operator,
    ))


@router.get("")
def valuation(
    keyword: str = "",
    warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None),
    brand: list[str] | None = Query(None),
    scope: str = Query("total", pattern="^(total|split)$"),
    missing_price: str = Query("all", pattern="^(all|retail|tax|core)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=100),
    ods: Session = Depends(get_ods_db),
    admin: Session = Depends(get_db),
) -> dict:
    filters = []
    params: dict = {}
    if keyword.strip():
        filters.append("(`货品编号` LIKE :keyword OR `货品名称` LIKE :keyword OR `条码` LIKE :keyword)")
        params["keyword"] = f"%{keyword.strip()}%"
    brands = sorted({value.strip() for value in brand or [] if value.strip()})
    if brands:
        keys = []
        for index, value in enumerate(brands):
            param = f"brand_{index}"
            params[param] = value
            keys.append(f":{param}")
        filters.append(f"`品牌` IN ({', '.join(keys)})")
    for field, values, key in (("仓库", warehouse if scope == "split" else None, "warehouse"), ("货品分类", product_type, "type")):
        values = sorted({value.strip() for value in values or [] if value.strip() and value != "__all__"})
        if values:
            keys = []
            for index, value in enumerate(values):
                param = f"{key}_{index}"
                params[param] = value
                keys.append(f":{param}")
            filters.append(f"`{field}` IN ({', '.join(keys)})")
    where = " AND ".join(filters) if filters else "1 = 1"
    source_table = "总库存查询" if scope == "total" else "分仓库查询"
    warehouse_column = "MAX(`仓库`)" if scope == "total" else "`仓库`"
    group_columns = "`货品编号`, `零售价`, `含税价`" if scope == "total" else "`货品编号`, `仓库`, `零售价`, `含税价`"
    stock_rows = ods.execute(text(f"""
        SELECT `货品编号` AS product_code, MAX(`货品名称`) AS product_name,
          MAX(`品牌`) AS brand, {warehouse_column} AS warehouse, MAX(`货品分类`) AS product_type,
          SUM(COALESCE(`库存数量`, 0)) AS stock,
          SUM(COALESCE(`可用库存`, 0)) AS available_stock,
          `零售价` AS retail_price, `含税价` AS tax_price,
          MAX(`updatetime`) AS updated_at
        FROM `{source_table}` WHERE {where}
        GROUP BY {group_columns}
        ORDER BY stock DESC, product_code, warehouse
    """), params).mappings().all()
    prices = current_prices(admin)
    rows = []
    latest = None
    for row in stock_rows:
        sku = str(row["product_code"] or "").strip()
        stock = int(row["stock"] or 0)
        revision = prices.get(sku)
        values = {"retail": row["retail_price"], "tax": row["tax_price"], "core": revision.price if revision else None}
        item = {
            "product_code": sku, "product_name": row["product_name"], "brand": row["brand"],
            "warehouse": row["warehouse"], "product_type": row["product_type"],
            "stock": stock, "available_stock": int(row["available_stock"] or 0),
            "core_effective_date": revision.effective_date.isoformat() if revision else None,
        }
        for key, value in values.items():
            valid = value is not None and Decimal(str(value)) > 0
            item[f"{key}_price"] = float(value) if valid else None
            item[f"{key}_amount"] = round(stock * float(value), 2) if valid else None
        if row["updated_at"] and (latest is None or row["updated_at"] > latest):
            latest = row["updated_at"]
        rows.append(item)
    if missing_price != "all":
        rows = [row for row in rows if row[f"{missing_price}_price"] is None]
    metrics = {key: {"amount": 0.0, "priced_stock": 0, "missing_stock": 0, "priced_rows": 0, "missing_rows": 0}
               for key in ("retail", "tax", "core")}
    for row in rows:
        for key in metrics:
            valid = row[f"{key}_price"] is not None
            bucket = metrics[key]
            bucket["priced_rows" if valid else "missing_rows"] += 1
            bucket["priced_stock" if valid else "missing_stock"] += row["stock"]
            if valid:
                bucket["amount"] += row[f"{key}_amount"]
    for bucket in metrics.values():
        bucket["amount"] = round(bucket["amount"], 2)
    return ok({
        "metrics": metrics,
        "stock": sum(row["stock"] for row in rows),
        "available_stock": sum(row["available_stock"] for row in rows),
        "updated_at": latest.isoformat() if latest else None,
        "pagination": {"page": page, "page_size": page_size, "total": len(rows)},
        "rows": rows[(page - 1) * page_size:page * page_size],
    })


@router.get("/export", dependencies=[Depends(require_permission("data.export"))])
def export_valuation(
    keyword: str = "", warehouse: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None), brand: list[str] | None = Query(None),
    scope: str = Query("total", pattern="^(total|split)$"),
    missing_price: str = Query("all", pattern="^(all|retail|tax|core)$"),
    ods: Session = Depends(get_ods_db), admin: Session = Depends(get_db),
) -> Response:
    data = valuation(keyword=keyword, warehouse=warehouse, product_type=product_type,
                     brand=brand, scope=scope, missing_price=missing_price, page=1, page_size=100_000,
                     ods=ods, admin=admin)["data"]
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("总库存估算" if scope == "total" else "分仓库存估算")
    headers = [
        ("product_code", "货品编号"), ("product_name", "货品名称"), ("brand", "品牌"),
        ("product_type", "分类"), ("warehouse", "仓库"), ("stock", "库存数量"),
        ("available_stock", "可用库存"), ("retail_price", "零售价"),
        ("tax_price", "含税价"), ("core_price", "核心成本价"),
        ("retail_amount", "零售价估值"), ("tax_amount", "含税价估值"),
        ("core_amount", "核心成本估值"), ("core_effective_date", "核心成本价生效日期"),
    ]
    header_format = workbook.add_format({"bold": True, "bg_color": "#E8F2EC"})
    money_format = workbook.add_format({"num_format": "#,##0.00"})
    sheet.write_row(0, 0, [label for _, label in headers], header_format)
    sheet.set_column(0, 0, 20)
    sheet.set_column(1, 1, 38)
    sheet.set_column(2, 4, 18)
    sheet.set_column(5, len(headers) - 1, 17)
    for index, row in enumerate(data["rows"], start=1):
        for column, (key, _) in enumerate(headers):
            value = row.get(key)
            if value is None:
                continue
            if key in {"product_code", "product_name", "brand", "product_type", "warehouse", "core_effective_date"}:
                sheet.write_string(index, column, str(value))
            elif key.endswith("_price") or key.endswith("_amount"):
                sheet.write_number(index, column, float(value), money_format)
            else:
                sheet.write_number(index, column, int(value))
    sheet.autofilter(0, 0, len(data["rows"]), len(headers) - 1)
    sheet.freeze_panes(1, 2)
    workbook.close()
    filename = quote(f"{'总库存' if scope == 'total' else '分仓库存'}价格估算_{date.today():%Y%m%d}.xlsx")
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.get("/prices", dependencies=[Depends(require_permission("inventory.price.manage"))])
def list_prices(
    keyword: str = "", brand: list[str] | None = Query(None), source: str = "all",
    effective_from: date | None = None, effective_to: date | None = None,
    min_price: Decimal | None = None, max_price: Decimal | None = None,
    ods: Session = Depends(get_ods_db), admin: Session = Depends(get_db),
) -> dict:
    prices = price_states(admin)[1] if source == "delete" else current_prices(admin)
    brands = price_brands(ods, list(prices))
    term = keyword.strip().lower()
    selected_brands = {value.strip() for value in brand or [] if value.strip()}
    rows = [dict(price_data(item), brand=brands.get(item.product_code, "")) for item in prices.values()
            if (not term or term in item.product_code.lower() or term in item.product_name.lower())
            and (not selected_brands or brands.get(item.product_code) in selected_brands)
            and (source in ("all", "delete") or item.source == source)
            and (effective_from is None or item.effective_date >= effective_from)
            and (effective_to is None or item.effective_date <= effective_to)
            and (min_price is None or item.price >= min_price)
            and (max_price is None or item.price <= max_price)]
    return ok(sorted(rows, key=lambda item: item["product_code"]))


@router.get("/prices/export", dependencies=[Depends(require_permission("inventory.price.manage"))])
def export_prices(
    keyword: str = "", brand: list[str] | None = Query(None), source: str = "all",
    effective_from: date | None = None, effective_to: date | None = None,
    min_price: Decimal | None = None, max_price: Decimal | None = None,
    ods: Session = Depends(get_ods_db), admin: Session = Depends(get_db),
) -> Response:
    rows = list_prices(keyword=keyword, brand=brand, source=source, effective_from=effective_from,
                       effective_to=effective_to, min_price=min_price, max_price=max_price,
                       ods=ods, admin=admin)["data"]
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("核心成本价")
    headers = ["货品编号", "货品名称", "品牌", "核心成本价"]
    header_format = workbook.add_format({"bold": True, "bg_color": "#E8F2EC"})
    money_format = workbook.add_format({"num_format": "#,##0.00"})
    for column, label in enumerate(headers):
        sheet.write(0, column, label, header_format)
    sheet.set_column(0, 0, 20)
    sheet.set_column(1, 1, 42)
    sheet.set_column(2, 3, 19)
    for index, row in enumerate(rows, start=1):
        sheet.write_string(index, 0, row["product_code"])
        sheet.write_string(index, 1, row["product_name"] or "")
        sheet.write_string(index, 2, row.get("brand") or "")
        sheet.write_number(index, 3, row["price"], money_format)
    sheet.autofilter(0, 0, len(rows), len(headers) - 1)
    sheet.freeze_panes(1, 2)
    workbook.close()
    filename = quote(f"核心成本价_{date.today():%Y%m%d}.xlsx")
    return Response(output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


@router.get("/prices/{product_code}/history", dependencies=[Depends(require_permission("inventory.price.manage"))])
def price_history(product_code: str, admin: Session = Depends(get_db)) -> dict:
    rows = admin.query(CoreCostPriceRevision).filter(
        CoreCostPriceRevision.product_code == product_code
    ).order_by(CoreCostPriceRevision.id.desc()).all()
    return ok([price_data(item) for item in rows])


@router.post("/prices", dependencies=[Depends(require_permission("inventory.price.manage"))])
def save_price(item: PriceInput, user: User = Depends(get_current_user), admin: Session = Depends(get_db)) -> dict:
    add_revision(admin, item, user.username, "manual")
    admin.commit()
    return ok({"saved": 1})


@router.delete("/prices/{product_code}", dependencies=[Depends(require_permission("inventory.price.manage"))])
def delete_price(product_code: str, user: User = Depends(get_current_user), admin: Session = Depends(get_db)) -> dict:
    current = current_prices(admin).get(product_code)
    if current is None:
        raise HTTPException(404, "当前核心成本价不存在")
    add_revision(admin, PriceInput(product_code=product_code, product_name=current.product_name,
                                   price=current.price, effective_date=date.today()), user.username, "delete")
    admin.commit()
    return ok({"deleted": 1})


@router.post("/prices/{product_code}/restore", dependencies=[Depends(require_permission("inventory.price.manage"))])
def restore_price(product_code: str, revision_id: int, user: User = Depends(get_current_user), admin: Session = Depends(get_db)) -> dict:
    revision = admin.get(CoreCostPriceRevision, revision_id)
    if revision is None or revision.product_code != product_code:
        raise HTTPException(404, "价格版本不存在")
    add_revision(admin, PriceInput(product_code=product_code, product_name=revision.product_name,
                                   price=revision.price, effective_date=date.today()),
                 user.username, "restore", revision.id)
    admin.commit()
    return ok({"restored": 1})


@router.post("/prices/import-preview", dependencies=[Depends(require_permission("inventory.price.manage"))])
async def import_preview(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    if len(content) > 5_000_000 or not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "请上传不超过 5 MB 的 xlsx 文件")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        sheet = workbook.active
        iterator = sheet.values
        header = next(iterator)
        columns = {str(value).strip(): index for index, value in enumerate(header) if value is not None}
        indexes = [columns[name] for name in ("货品编号", "货品名称", "品牌", "核心成本价")]
        rows = []
        errors = []
        seen = set()
        blank_price_count = 0
        for number, raw in enumerate(iterator, start=2):
            if number > 5001:
                raise HTTPException(400, "一次最多导入 5000 行")
            if not any(value is not None for value in raw):
                continue
            code = str(raw[indexes[0]] or "").strip()
            name = str(raw[indexes[1]] or "").strip()
            brand = str(raw[indexes[2]] or "").strip()
            value = raw[indexes[3]]
            if not code or code in seen or len(code) > 128:
                errors.append(f"第 {number} 行货品编号为空、重复或过长")
                continue
            seen.add(code)
            if value is None or value == "":
                blank_price_count += 1
                continue
            try:
                price = Decimal(str(value))
                item = PriceInput(product_code=code, product_name=name[:255], price=price,
                                  effective_date=date.today())
                rows.append({**item.model_dump(mode="json"), "brand": brand})
            except (InvalidOperation, ValueError):
                errors.append(f"第 {number} 行核心成本价无效")
        return ok({"rows": rows, "errors": errors, "blank_price_count": blank_price_count})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, "Excel 格式或表头不正确") from exc


@router.post("/prices/import", dependencies=[Depends(require_permission("inventory.price.manage"))])
def import_prices(payload: ImportInput, user: User = Depends(get_current_user), admin: Session = Depends(get_db)) -> dict:
    codes = [item.product_code.strip() for item in payload.rows]
    if len(codes) != len(set(codes)):
        raise HTTPException(400, "导入数据包含重复货品编号")
    existing = current_prices(admin)
    saved = 0
    for item in payload.rows:
        previous = existing.get(item.product_code.strip())
        if previous and previous.price == item.price and previous.product_name == item.product_name:
            continue
        add_revision(admin, item, user.username, "import")
        saved += 1
    admin.commit()
    return ok({"saved": saved, "skipped": len(codes) - saved})
