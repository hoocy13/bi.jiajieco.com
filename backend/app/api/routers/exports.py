from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routers import inventory, sales
from app.db.ods import get_ods_db
from app.models.user import User
from app.services.excel_export import ExportColumn, create_excel_export


router = APIRouter(prefix="/exports", tags=["exports"])
MAX_EXPORT_ROWS = 50_000
EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportRequest(BaseModel):
    filters: dict[str, Any] = Field(default_factory=dict)


class CustomColumn(BaseModel):
    key: str
    label: str
    kind: str = "text"
    width: int = 16


class CustomExportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    rows: list[dict[str, Any]] = Field(max_length=MAX_EXPORT_ROWS)
    columns: list[CustomColumn] = Field(min_length=1, max_length=60)
    filters: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list, max_length=20)


def _date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"日期格式不正确：{value}") from exc


def _text(value: object) -> str | None:
    text = str(value).strip() if value not in (None, "") else ""
    return text or None


def _texts(value: object) -> list[str] | None:
    if value in (None, ""):
        return None
    values = value if isinstance(value, list) else [value]
    result = [str(item).strip() for item in values if str(item).strip()]
    return result or None


def _int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unwrap(result: dict) -> dict:
    data = result.get("data")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="导出查询返回格式不正确")
    if data.get("scope_required"):
        raise HTTPException(status_code=400, detail="请先选择分析范围，再导出数据")
    return data


def _check_limit(rows: list[dict], total: object) -> None:
    if _int(total, len(rows)) > MAX_EXPORT_ROWS or len(rows) > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"当前筛选结果超过 {MAX_EXPORT_ROWS:,} 条，请缩小筛选范围后再导出",
        )


def _filter_summary(filters: dict[str, Any], labels: dict[str, str]) -> dict[str, object]:
    return {
        labels[key]: ("全部" if value in (None, "", []) else value)
        for key, value in filters.items()
        if key in labels
    }


def _sales_detail(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    result = sales.sales_detail(
        Response(),
        range=str(filters.get("range") or "last_30"),
        start_date=_date(filters.get("start_date")),
        end_date=_date(filters.get("end_date")),
        page=1,
        page_size=MAX_EXPORT_ROWS + 1,
        keyword=_text(filters.get("keyword")),
        channel=_text(filters.get("channel")),
        status=_text(filters.get("status")),
        current_user=user,
        db=db,
        _export=True,
    )
    data = _unwrap(result)
    columns = (
        ExportColumn("date", "日期", "date", 12), ExportColumn("order_no", "订单编号", width=22),
        ExportColumn("channel", "销售渠道", width=18), ExportColumn("product", "商品摘要", width=42),
        ExportColumn("quantity", "数量", "integer", 12), ExportColumn("paid_amount", "实付金额", "number", 16),
        ExportColumn("receivable_amount", "应收合计", "number", 16), ExportColumn("status", "订单状态", width=14),
        ExportColumn("settlement_status", "结算状态", width=14), ExportColumn("city", "城市", width=12),
    )
    labels = {"range": "时间范围", "start_date": "开始日期", "end_date": "结束日期", "keyword": "关键词", "channel": "销售渠道", "status": "订单状态"}
    notes = ("数据口径与销售明细页面当前筛选条件一致。", "订单编号按文本写入，避免长编号被 Excel 转为科学计数法。", "最多导出 50,000 条记录。")
    return data, columns, _filter_summary(filters, labels), notes


def _customer_analysis(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    result = sales.sales_customer_analysis(
        Response(), direction=str(filters.get("direction") or "brand"), range=str(filters.get("range") or "last_30"),
        start_date=_date(filters.get("start_date")), end_date=_date(filters.get("end_date")),
        brand=_text(filters.get("brand")), channel=_text(filters.get("channel")),
        channel_type=_text(filters.get("channel_type")), owner=_text(filters.get("owner")),
        keyword=_text(filters.get("keyword")), frequency=str(filters.get("frequency") or "all"),
        page=1, page_size=MAX_EXPORT_ROWS + 1, current_user=user, db=db, _export=True,
    )
    data = _unwrap(result)
    columns = (
        ExportColumn("customer_code", "客户编号", width=22), ExportColumn("customer_name", "客户名称", width=28),
        ExportColumn("orders", "订单数", "integer", 12), ExportColumn("active_days", "下单天数", "integer", 12),
        ExportColumn("avg_interval_days", "平均下单间隔（天）", "number", 20), ExportColumn("last_order_date", "最近下单日期", "date", 16),
        ExportColumn("quantity", "净销售数量", "integer", 14), ExportColumn("paid_amount", "销售额", "number", 16),
    )
    labels = {"direction": "分析方向", "range": "时间范围", "start_date": "开始日期", "end_date": "结束日期", "brand": "品牌", "channel": "渠道", "channel_type": "渠道分类", "owner": "渠道负责人", "keyword": "客户关键词", "frequency": "客户分层"}
    notes = ("数据口径与客户分析页面当前筛选条件一致。", "仅统计可识别客户；客户编号按文本写入。", "首购、稳定、高频客户沿用页面现有分层规则。")
    return data, columns, _filter_summary(filters, labels), notes


def _customer_churn(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    result = sales.sales_customer_churn_alerts(
        Response(), direction=str(filters.get("direction") or "brand"), brand=_text(filters.get("brand")),
        channel=_text(filters.get("channel")), channel_type=_text(filters.get("channel_type")), owner=_text(filters.get("owner")),
        keyword=_text(filters.get("keyword")), inactive_months=_int(filters.get("inactive_months"), 3),
        min_historical_orders=_int(filters.get("min_historical_orders"), 4), page=1, page_size=MAX_EXPORT_ROWS + 1,
        current_user=user, db=db, _export=True,
    )
    data = _unwrap(result)
    level = {"critical": "重点召回", "high": "高风险", "watch": "关注"}
    data["rows"] = [{**row, "alert_level_text": level.get(row.get("alert_level"), row.get("alert_level")), "high_value_text": "是" if row.get("is_high_value") else "否"} for row in data.get("rows", [])]
    columns = (
        ExportColumn("alert_level_text", "预警等级", width=14), ExportColumn("customer_code", "客户编号", width=22),
        ExportColumn("customer_name", "客户名称", width=28), ExportColumn("historical_orders", "历史订单数", "integer", 14),
        ExportColumn("active_days", "历史下单天数", "integer", 16), ExportColumn("avg_interval_days", "平均下单间隔（天）", "number", 20),
        ExportColumn("last_order_date", "最近下单日期", "date", 16), ExportColumn("inactive_days", "未下单天数", "integer", 14),
        ExportColumn("historical_amount", "历史销售额", "number", 16), ExportColumn("high_value_text", "高价值客户", width=14),
    )
    labels = {"direction": "分析方向", "brand": "品牌", "channel": "渠道", "channel_type": "渠道分类", "owner": "渠道负责人", "keyword": "客户关键词", "inactive_months": "未下单周期（月）", "min_historical_orders": "最低历史订单数"}
    notes = ("数据口径与客户流失预警页面当前筛选条件一致。", "历史观察期、未下单周期和预警规则沿用页面现有口径。", "客户编号按文本写入。")
    return data, columns, _filter_summary(filters, labels), notes


def _slow_moving(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    result = inventory.slow_moving_inventory(
        Response(), keyword=_text(filters.get("keyword")), barcode=_text(filters.get("barcode")),
        warehouse=_texts(filters.get("warehouse")), product_type=_texts(filters.get("product_type")),
        snapshot_date=_date(filters.get("snapshot_date")), period_days=_int(filters.get("period_days"), 90),
        risk_scope=str(filters.get("risk_scope") or "slow_all"), retention_scope=str(filters.get("retention_scope") or "all"),
        sort_by=str(filters.get("sort_by") or "stock"), sort_order=str(filters.get("sort_order") or "desc"),
        page=1, page_size=MAX_EXPORT_ROWS + 1, current_user=user, db=db, _export=True,
    )
    data = _unwrap(result)
    columns = (
        ExportColumn("risk_label", "风险", width=14), ExportColumn("product", "商品", width=42),
        ExportColumn("product_code", "货品编号", width=22), ExportColumn("barcode", "货品条码", width=22),
        ExportColumn("brand", "品牌", width=18), ExportColumn("product_type", "分类", width=12),
        ExportColumn("warehouse_count", "仓库数", "integer", 12), ExportColumn("stock", "截止库存", "integer", 14),
        ExportColumn("period_sales", "周期净销量", "integer", 14), ExportColumn("estimated_days", "预计库存天数", "number", 16),
        ExportColumn("ending_stock_ratio", "库存留存率", "percent", 16),
    )
    labels = {"keyword": "商品关键词", "barcode": "货品条码", "warehouse": "仓库", "product_type": "货品分类", "snapshot_date": "截止日期", "period_days": "观察周期（天）", "risk_scope": "风险范围", "retention_scope": "留存率范围", "sort_by": "排序字段", "sort_order": "排序方向"}
    notes = ("数据口径与滞销分析页面当前筛选条件一致。", "截止库存使用所选已完成库存快照；周期净销量按截止日前观察周期统计。", "库存留存率 = 截止库存 ÷（截止库存 + 周期正向销量）。金额暂不纳入滞销分析。", "货品编号和条码按文本写入。")
    return data, columns, _filter_summary(filters, labels), notes


def _inventory_health(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    data = _unwrap(inventory.inventory_health(
        Response(), keyword=_text(filters.get("keyword")), barcode=_text(filters.get("barcode")),
        warehouse=_texts(filters.get("warehouse")), product_type=_texts(filters.get("product_type")),
        issue_type=str(filters.get("issue_type") or "all"), page=1, page_size=MAX_EXPORT_ROWS + 1,
        current_user=user, db=db,
    ))
    columns = (
        ExportColumn("product", "商品", width=42), ExportColumn("product_code", "货品编号", width=22),
        ExportColumn("barcode", "货品条码", width=22), ExportColumn("brand", "品牌", width=18),
        ExportColumn("product_type", "分类", width=12), ExportColumn("warehouse", "仓库", width=20),
        ExportColumn("stock", "库存数量", "integer", 14), ExportColumn("available_stock", "可用库存", "integer", 14),
        ExportColumn("sales30", "近30天销量", "integer", 14), ExportColumn("sales90", "近90天销量", "integer", 14),
        ExportColumn("available_days", "预计可售天数", "number", 16), ExportColumn("issue_label", "健康问题", width=18),
    )
    labels = {"keyword": "商品关键词", "barcode": "货品条码", "warehouse": "仓库", "product_type": "货品分类", "issue_type": "问题类型"}
    return data, columns, _filter_summary(filters, labels), ("数据口径与库存健康度页面当前筛选条件一致。", "库存优先使用可用库存；编号和条码按文本写入。")


def _inventory_turnover(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    data = _unwrap(inventory.inventory_turnover(
        Response(), keyword=_text(filters.get("keyword")), barcode=_text(filters.get("barcode")),
        min_stock=_int(filters.get("min_stock"), 100), warehouse=_texts(filters.get("warehouse")),
        product_type=_texts(filters.get("product_type")), page=1, page_size=MAX_EXPORT_ROWS + 1,
        current_user=user, db=db,
    ))
    columns = (
        ExportColumn("rank", "排名", "integer", 10), ExportColumn("product", "商品", width=42),
        ExportColumn("product_code", "货品编号", width=22), ExportColumn("barcode", "货品条码", width=22),
        ExportColumn("brand", "品牌", width=18), ExportColumn("product_type", "货品分类", width=12),
        ExportColumn("warehouse", "仓库", width=20), ExportColumn("stock", "库存数量", "integer", 14),
        ExportColumn("available_stock", "可用库存", "integer", 14), ExportColumn("sales30", "近30天销量", "integer", 14),
        ExportColumn("turnover_days", "周转天数", "number", 14), ExportColumn("status", "状态", width=12),
    )
    labels = {"keyword": "商品关键词", "barcode": "货品条码", "min_stock": "最低库存", "warehouse": "仓库", "product_type": "货品分类"}
    return data, columns, _filter_summary(filters, labels), ("数据口径与商品周转页面当前筛选条件一致。", "周转天数越长表示周转越慢；编号和条码按文本写入。")


def _batch_expiry(filters: dict[str, Any], user: User, db: Session, long_expiry: bool = False) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    data = _unwrap(inventory.batch_expiry_analysis(
        Response(), keyword=_text(filters.get("keyword")), barcode=_text(filters.get("barcode")),
        warehouse=_texts(filters.get("warehouse")), product_type=_texts(filters.get("product_type")),
        expiry_range=str(filters.get("expiry_range") or "all"), page=1, long_page=1,
        page_size=MAX_EXPORT_ROWS + 1, current_user=user, db=db,
    ))
    if long_expiry:
        data["rows"] = data.get("long_expiry_rows") or []
        data["pagination"] = data.get("long_pagination") or {"total": len(data["rows"])}
        columns = (
            ExportColumn("rank", "排名", "integer", 10), ExportColumn("warehouse", "仓库", width=20),
            ExportColumn("product", "商品", width=42), ExportColumn("product_code", "货品编号", width=22),
            ExportColumn("barcode", "货品条码", width=22), ExportColumn("brand", "品牌", width=18),
            ExportColumn("product_type", "货品分类", width=12), ExportColumn("batch_count", "批次数", "integer", 12),
            ExportColumn("nearest_expiry_date", "最近到期日", "date", 16), ExportColumn("remaining_months", "剩余月数", "number", 14),
            ExportColumn("available_stock", "可用库存", "integer", 14),
        )
    else:
        data["rows"] = data.get("fefo_rows") or []
        columns = (
            ExportColumn("rank", "顺序", "integer", 10), ExportColumn("warehouse", "仓库", width=20),
            ExportColumn("product", "商品", width=42), ExportColumn("product_code", "货品编号", width=22),
            ExportColumn("barcode", "货品条码", width=22), ExportColumn("brand", "品牌", width=18),
            ExportColumn("product_type", "货品分类", width=12), ExportColumn("batch", "批次", width=18),
            ExportColumn("production_date", "生产日期", "date", 16), ExportColumn("expiry_date", "到期日期", "date", 16),
            ExportColumn("remaining_days", "剩余效期（天）", "integer", 16), ExportColumn("available_stock", "可用库存", "integer", 14),
            ExportColumn("fefo_rank", "FEFO顺位", "integer", 12), ExportColumn("status", "效期状态", width=16),
        )
    labels = {"keyword": "商品关键词", "barcode": "货品条码", "warehouse": "仓库", "product_type": "货品分类", "expiry_range": "效期范围"}
    return data, columns, _filter_summary(filters, labels), ("数据口径与批次效期分析页面当前筛选条件一致。", "按 FEFO 原则优先处理临近到期批次；编号、条码和批次按文本写入。")


def _batch_expiry_fefo(filters: dict[str, Any], user: User, db: Session):
    return _batch_expiry(filters, user, db, False)


def _batch_expiry_long(filters: dict[str, Any], user: User, db: Session):
    return _batch_expiry(filters, user, db, True)


def _brand_arrivals(filters: dict[str, Any], user: User, db: Session) -> tuple[dict, tuple[ExportColumn, ...], dict, tuple[str, ...]]:
    data = _unwrap(inventory.brand_monthly_arrivals(
        Response(), start_date=_date(filters.get("start_date")), end_date=_date(filters.get("end_date")),
        brand=_texts(filters.get("brand")), product_type=_texts(filters.get("product_type")),
        warehouse=_texts(filters.get("warehouse")), detail_product_type=_text(filters.get("detail_product_type")),
        page=1, page_size=MAX_EXPORT_ROWS + 1, current_user=user, db=db,
    ))
    data["rows"] = data.get("details") or []
    columns = (
        ExportColumn("receipt_time", "入库时间", width=20), ExportColumn("receipt_number", "入库单号", width=22),
        ExportColumn("brand", "品牌", width=18), ExportColumn("product", "货品名称", width=42),
        ExportColumn("product_code", "货品编号", width=22), ExportColumn("product_type", "货品分类", width=12),
        ExportColumn("warehouse", "入库仓库", width=20), ExportColumn("supplier", "供应商", width=24),
        ExportColumn("quantity", "到货数量", "integer", 14), ExportColumn("unit_cost", "成本单价", "number", 14),
        ExportColumn("cost_amount", "到货成本金额", "number", 18), ExportColumn("batch", "批次", width=18),
        ExportColumn("expiry_date", "到期日期", "date", 16),
    )
    labels = {"start_date": "开始日期", "end_date": "结束日期", "brand": "品牌", "product_type": "货品分类", "warehouse": "入库仓库", "detail_product_type": "明细分类"}
    return data, columns, _filter_summary(filters, labels), ("数据口径与品牌月度到货明细当前筛选条件一致。", "红冲和负数记录纳入净数量、净成本计算；入库单号、货品编号和批次按文本写入。")


EXPORTERS: dict[str, tuple[str, Callable]] = {
    "sales-detail": ("销售明细", _sales_detail),
    "customer-analysis": ("客户分析", _customer_analysis),
    "customer-churn-alerts": ("客户流失预警", _customer_churn),
    "slow-moving": ("滞销分析", _slow_moving),
    "inventory-health": ("库存健康度", _inventory_health),
    "inventory-turnover": ("商品周转", _inventory_turnover),
    "batch-expiry-fefo": ("批次效期_FEFO明细", _batch_expiry_fefo),
    "batch-expiry-long": ("批次效期_长效期明细", _batch_expiry_long),
    "brand-arrivals": ("品牌月度到货明细", _brand_arrivals),
}


@router.post("/custom")
def export_custom_dataset(
    request: CustomExportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    del current_user
    columns = tuple(ExportColumn(item.key, item.label, item.kind, item.width) for item in request.columns)
    path = create_excel_export(
        title=request.title,
        columns=columns,
        rows=request.rows,
        filters=request.filters,
        notes=tuple(request.notes) or ("导出当前页面已加载的完整分析数据。",),
    )
    background_tasks.add_task(Path(path).unlink, missing_ok=True)
    filename = f"{request.title}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return FileResponse(path, media_type=EXCEL_MEDIA_TYPE, filename=filename, background=background_tasks)


@router.post("/{dataset}")
def export_dataset(
    dataset: str,
    request: ExportRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_ods_db),
) -> FileResponse:
    exporter = EXPORTERS.get(dataset)
    if exporter is None:
        raise HTTPException(status_code=404, detail="不支持该导出类型")
    title, build = exporter
    data, columns, filter_summary, notes = build(request.filters, current_user, db)
    rows = data.get("rows") or []
    total = data.get("total", data.get("pagination", {}).get("total", len(rows)))
    _check_limit(rows, total)
    path = create_excel_export(title=title, columns=columns, rows=rows, filters=filter_summary, notes=notes)
    background_tasks.add_task(Path(path).unlink, missing_ok=True)
    filename = f"{title}_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return FileResponse(path, media_type=EXCEL_MEDIA_TYPE, filename=filename, background=background_tasks)
