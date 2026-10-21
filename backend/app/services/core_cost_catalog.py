from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import text


def load_catalog(ods, codes: list[str] | None = None) -> dict[str, dict]:
    """Total stock is authoritative; split stock supplies otherwise absent SKUs only."""
    catalog = {}
    batches = [None] if codes is None else [codes[i:i + 500] for i in range(0, len(codes), 500)]
    for table in ("总库存查询", "分仓库查询"):
        grouped = defaultdict(list)
        for batch in batches:
            params = {f"code_{i}": value for i, value in enumerate(batch or [])}
            where = "WHERE `货品编号` IN (" + ",".join(f":{key}" for key in params) + ")" if batch is not None else ""
            rows = ods.execute(text(f"""
                SELECT DISTINCT `货品编号` AS product_code, `货品名称` AS product_name,
                    `品牌` AS brand, `货品分类` AS product_type, `条码` AS barcode,
                    `零售价` AS retail_price, `含税价` AS tax_price
                FROM `{table}` {where}
            """), params).mappings()
            for row in rows:
                code = str(row["product_code"] or "").strip()
                if code and code not in catalog:
                    grouped[code].append(dict(row))
        for code, rows in grouped.items():
            item = {"product_code": code, "catalog_source": table}
            for field in ("product_name", "brand", "product_type", "barcode"):
                values = sorted({str(row[field] or "").strip() for row in rows} - {""})
                item[field] = " / ".join(values)
            for field in ("retail_price", "tax_price"):
                values = sorted({Decimal(str(row[field])) for row in rows if row[field] is not None and Decimal(str(row[field])) > 0})
                item[field] = values[0] if len(values) == 1 else None
                item[field + "_conflict"] = len(values) > 1
            catalog[code] = item
    return catalog


def calculate_cost(retail, discount):
    result = (Decimal(str(retail)) * Decimal(str(discount)) / 10).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if result <= 0 or result >= Decimal("10000000000000000"):
        raise HTTPException(422, "计算后的核心成本价超出有效范围")
    return result


def resolve_price(item, catalog: dict, existing: dict):
    current = existing.get(item.product_code)
    if "expected_revision_id" in item.model_fields_set and item.expected_revision_id != (current.id if current else None):
        raise HTTPException(409, f"{item.product_code} 的成本版本已变化，请重新预览")
    product = catalog.get(item.product_code, {})
    retail = product.get("retail_price")
    if item.pricing_mode == "discount":
        if product.get("retail_price_conflict"):
            raise HTTPException(422, f"{item.product_code} 零售价冲突，请先核对源资料或直接填价")
        if retail is None:
            raise HTTPException(422, f"{item.product_code} 缺少有效零售价，不能按折扣计算")
        if item.base_retail_price is not None and item.base_retail_price != retail:
            raise HTTPException(409, f"{item.product_code} 零售价已变化，请重新预览")
        price = calculate_cost(retail, item.discount)
        if item.price is not None and item.price != price:
            raise HTTPException(422, f"{item.product_code} 成本价与零售价×折扣不一致")
    else:
        price = item.price
    return item.model_copy(update={
        "product_name": (product.get("product_name") or item.product_name)[:255],
        "price": price, "base_retail_price": retail,
        "barcode": product.get("barcode") or (current.barcode if current else None),
    })
