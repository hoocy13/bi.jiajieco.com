from datetime import date
from io import BytesIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session
import xlsxwriter

from app.api.deps import require_permission
from app.api.routers.inventory_valuation import current_prices
from app.db.sales_profit import get_sales_profit_db
from app.db.ods import get_ods_db
from app.db.session import get_db
from app.schemas.common import ok
from app.services.sales_profit import AnalysisParams, SORT_FIELDS, analyze


router = APIRouter(prefix="/sales/profit-analysis", tags=["sales-profit"])


def analysis_params(
    view: str = Query("profit", pattern="^(profit|prices)$"),
    range: str = Query("month", pattern="^(month|custom)$"),
    start_date: date | None = None, end_date: date | None = None,
    owner: str = Query("", max_length=128),
    brand: list[str] | None = Query(None),
    channel_type: str = Query("all", pattern="^(all|online|offline)$"),
    channel: list[str] | None = Query(None), product_type: list[str] | None = Query(None),
    customer_keyword: str = Query("", max_length=255), keyword: str = Query("", max_length=255),
    group_by: str = Query("owner", pattern="^(owner|brand|channel|customer|product)$"),
    benchmark: str = Query("company", pattern="^(company|peers|previous)$"),
    price_direction: str = Query("all", pattern="^(all|above|below|unmatched)$"),
    cost_status: str = Query("all", pattern="^(all|priced|missing|loss)$"),
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=10, le=100),
    sort_by: str = Query("", pattern="^(|" + "|".join(sorted(SORT_FIELDS)) + ")$"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
) -> AnalysisParams:
    for values in (brand, channel, product_type):
        if values and (len(values) > 100 or any(len(value) > 255 for value in values)):
            raise HTTPException(422, "筛选值过多或过长")
    return AnalysisParams(
        view=view, range=range, start_date=start_date, end_date=end_date, owner=owner.strip(),
        brand=tuple(sorted({value.strip() for value in brand or [] if value.strip()})),
        channel_type=channel_type,
        channel=tuple(sorted({value.strip() for value in channel or [] if value.strip()})),
        product_type=tuple(sorted({value.strip() for value in product_type if value.strip()})) if product_type is not None else ("正装", "小样"),
        customer_keyword=customer_keyword.strip(), keyword=keyword.strip(), group_by=group_by,
        benchmark=benchmark if view == "prices" else "company",
        price_direction=price_direction if view == "prices" else "all", cost_status=cost_status,
        page=page, page_size=page_size, sort_by=sort_by, sort_order=sort_order,
    )


@router.get("")
def profit_analysis(
    params: AnalysisParams = Depends(analysis_params),
    ads: Session = Depends(get_sales_profit_db), ods: Session = Depends(get_ods_db),
    admin: Session = Depends(get_db),
) -> dict:
    return ok(analyze(ads, ods, current_prices(admin), params))


@router.get("/export", dependencies=[Depends(require_permission("data.export"))])
def export_analysis(
    params: AnalysisParams = Depends(analysis_params),
    ads: Session = Depends(get_sales_profit_db), ods: Session = Depends(get_ods_db),
    admin: Session = Depends(get_db),
) -> Response:
    data = analyze(ads, ods, current_prices(admin), params, export=True)
    headers = [
        ("owner", "销售人"), ("customer_code", "客户编号"), ("customer_name", "客户名称"),
        ("product_code", "货品编号"), ("product_name", "货品名称"), ("brand", "品牌"),
        ("product_type", "货品分类"), ("channel_type", "线上/线下"), ("channel", "具体渠道"),
        ("quantity", "净销售数量"), ("paid_amount", "净销售额"),
        ("sale_quantity", "正常销售数量"), ("sale_amount", "正常销售额"),
        ("return_quantity", "退货红冲数量"), ("return_amount", "退货红冲金额"),
        ("avg_price", "成交均价"), ("core_cost", "当前核心成本价"),
        ("estimated_cost", "预估成本"), ("estimated_profit", "预估毛利"), ("margin_rate", "预估毛利率(%)"),
        ("reference_price", "参考价"), ("reference_quantity", "参考销售数量"),
        ("price_delta", "价差"), ("price_delta_rate", "价差比例(%)"), ("price_effect_amount", "价差影响金额"),
    ]
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    sheet = workbook.add_worksheet("客户价格对比" if params.view == "prices" else "预估毛利分析")
    header_format = workbook.add_format({"bold": True, "bg_color": "#FCE8EF", "font_color": "#334155"})
    number_format = workbook.add_format({"num_format": "#,##0.00"})
    quantity_format = workbook.add_format({"num_format": "#,##0"})
    text_format = workbook.add_format({"num_format": "@"})
    sheet.write_row(0, 0, [label for _, label in headers], header_format)
    for row_index, row in enumerate(data["rows"], start=1):
        for column, (key, _) in enumerate(headers):
            value = row.get(key)
            if value is None:
                sheet.write_blank(row_index, column, None, number_format)
            elif isinstance(value, (int, float)):
                sheet.write_number(row_index, column, value, quantity_format if "quantity" in key else number_format)
            else:
                sheet.write_string(row_index, column, str(value), text_format)
    sheet.freeze_panes(1, 5)
    sheet.autofilter(0, 0, len(data["rows"]), len(headers) - 1)
    sheet.set_column(0, len(headers) - 1, 18)
    sheet.set_column(2, 2, 26)
    sheet.set_column(4, 4, 42)
    metadata = workbook.add_worksheet("统计口径")
    metadata.write_column(0, 0, ["开始日期", "结束日期", "成本日期", "销售人归属", "毛利口径", "成交均价", "成本覆盖率", "参考价", "低于成本销售额"])
    metadata.write_column(0, 1, [
        data["start_date"], data["end_date"], data["cost_as_of"], "当前渠道负责人，并非订单业务员",
        "净分摊销售额减净数量乘当前核心成本价；缺成本不计毛利，非历史实际毛利或净利润",
        "正常正向交易销售额除销售数量，退货红冲不参与均价",
        "有核心成本的正常销售额占全部正常销售额比例",
        {"company": "公司已识别客户同 SKU、同品牌、同分类、同线上/线下加权均价", "peers": "同销售人其他客户同 SKU、同品牌、同分类、同线上/线下加权均价", "previous": "同销售人、同客户、同 SKU、同品牌、同分类、同线上/线下上期加权均价"}[params.benchmark],
        "客户、商品、具体渠道分组后的正常成交均价低于当前核心成本价的销售额",
    ])
    metadata.set_column(0, 0, 22)
    metadata.set_column(1, 1, 100)
    workbook.close()
    filename = f"{'客户价格对比' if params.view == 'prices' else '销售预估毛利'}_{data['start_date']}_{data['end_date']}.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
    })
