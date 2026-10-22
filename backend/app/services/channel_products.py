"""Read-only channel product drilldown, retaining signed sales and returns."""
from sqlalchemy import text


def load_channel_products(db, *, channel, start, end, keyword="", product_type="",
                          page=1, page_size=20, sort="paid_amount", direction="descending", version=None):
    params = dict(channel=channel, start=start, end=end, limit=page_size, offset=(page-1)*page_size)
    if version is not None:
        source = "ads_sales_daily_brand_channel_product"
        fields = dict(product="product", brand="brand", product_type="product_type")
        amount, quantity = "paid_amount", "quantity"
        filters = ["data_version=:version", "sales_date BETWEEN :start AND :end", "channel=:channel"]
        params["version"] = version
    else:
        source = "`dwd`.`销售单明细账_品牌补全`"
        fields = dict(product="`货品名称`", brand="`品牌`", product_type="`货品分类`")
        amount, quantity = "`分摊后金额`", "`数量`"
        filters = ["`下单时间`>=:start", "`下单时间`<DATE_ADD(:end, INTERVAL 1 DAY)",
                   "COALESCE(NULLIF(`销售渠道`, ''), '未归类')=:channel"]
    if keyword.strip():
        filters.append(f"({fields['product']} LIKE :keyword OR {fields['brand']} LIKE :keyword)")
        params["keyword"] = "%"+keyword.strip()+"%"
    if product_type:
        filters.append(f"{fields['product_type']}=:product_type")
        params["product_type"] = product_type
    dimensions = [f"COALESCE(NULLIF({field}, ''), '未分类')" for field in fields.values()]
    select = ", ".join(f"{expression} AS {name}" for name, expression in zip(fields, dimensions))
    grouped = (f"SELECT {select}, SUM(COALESCE({amount},0)) AS paid_amount, "
               f"SUM(COALESCE({quantity},0)) AS quantity FROM {source} "
               f"WHERE {' AND '.join(filters)} GROUP BY {', '.join(dimensions)}")
    summary = dict(db.execute(text(f"SELECT COUNT(*) AS products, COALESCE(SUM(paid_amount),0) AS paid_amount, "
                                  f"COALESCE(SUM(quantity),0) AS quantity FROM ({grouped}) p"), params).mappings().one())
    sort = sort if sort in {*fields, "paid_amount", "quantity"} else "paid_amount"
    order = "ASC" if direction == "ascending" else "DESC"
    rows = [dict(r) for r in db.execute(text(f"SELECT * FROM ({grouped}) p ORDER BY {sort} {order}, "
                                           "brand, product_type, product LIMIT :limit OFFSET :offset"), params).mappings()]
    total_amount = float(summary["paid_amount"])
    for row in rows:
        row["share"] = float(row["paid_amount"])/total_amount*100 if total_amount else 0
    return dict(channel_name=channel, start_date=str(start), end_date=str(end), data_version=version,
                summary=summary, rows=rows, pagination=dict(page=page,page_size=page_size,total=int(summary["products"])))
