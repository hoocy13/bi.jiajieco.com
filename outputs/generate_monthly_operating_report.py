from __future__ import annotations

import argparse
import base64
import calendar
import gzip
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(os.environ.get("BI_PROJECT_ROOT", Path(__file__).resolve().parents[1]))
OUTPUT_DIR = PROJECT_ROOT / "outputs"
EXTRACTOR = OUTPUT_DIR / "extract_monthly_operating_report_v2.py"
TEMPLATE = OUTPUT_DIR / "monthly_report_template.json"
HTML_SHELL = OUTPUT_DIR / "monthly_report_shell.html"


def ratio(current: float, base: float) -> float | None:
    return current / base - 1 if base else None


def pct(value: float | None) -> str:
    return "不可比" if value is None else f"{abs(value) * 100:.1f}%"


def movement(value: float | None) -> str:
    if value is None:
        return "不可比"
    return ("增长" if value >= 0 else "下降") + pct(value)


def wan(value: float) -> str:
    return f"{value / 10_000:,.2f}万元"


def yi(value: float) -> str:
    return f"{value / 100_000_000:.2f}亿元" if abs(value) >= 100_000_000 else wan(value)


def month_text(iso_date: str) -> str:
    year, month, _ = iso_date.split("-")
    return f"{int(year)}年{int(month)}月"


def load_raw(month: str) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(EXTRACTOR), "--month", month],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(result.stdout)


def validate_raw(raw: dict) -> None:
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    current = raw["periods"][-1]
    report_end = datetime.fromisoformat(current["end_date"]).date()
    if report_end >= today:
        raise ValueError(f"报告月份尚未完整结束：{current['start_date']} 至 {current['end_date']}")
    for item in raw["periods"]:
        start = datetime.fromisoformat(item["start_date"]).date()
        expected_days = calendar.monthrange(start.year, start.month)[1]
        summary = item["summary"]
        if (
            int(summary["day_rows"] or 0) != expected_days
            or summary.get("min_date") != item["start_date"]
            or summary.get("max_date") != item["end_date"]
        ):
            raise ValueError(f"销售日数据不完整，停止生成：{item['start_date']} 至 {item['end_date']}")
        snapshot = item["inventory_snapshot"]
        if not snapshot.get("snapshot_date") or snapshot.get("stock_quantity") is None:
            raise ValueError(f"缺少成功的月末库存快照，停止生成：{item['end_date']}")


def block_map(artifact: dict) -> dict[str, dict]:
    return {item["id"]: item for item in artifact["manifest"]["blocks"]}


def chart_map(artifact: dict) -> dict[str, dict]:
    return {item["id"]: item for item in artifact["manifest"]["charts"]}


def source_map(artifact: dict) -> dict[str, dict]:
    return {item["id"]: item for item in artifact["manifest"]["sources"]}


def build_artifact(month: str, raw: dict) -> dict:
    artifact = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    periods = raw["periods"]
    yoy_raw, previous_raw, current_raw = periods
    yoy_name = month_text(yoy_raw["start_date"])
    previous_name = month_text(previous_raw["start_date"])
    current_name = month_text(current_raw["start_date"])
    month_number = int(current_raw["start_date"][5:7])
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")

    def summary(item: dict) -> dict:
        row = item["summary"]
        amount = float(row["paid_amount"] or 0)
        orders = int(row["orders"] or 0)
        quantity = float(row["quantity"] or 0)
        return {
            "paid_amount": amount,
            "orders": orders,
            "quantity": quantity,
            "avg_order_amount": amount / orders if orders else 0,
        }

    yoy = summary(yoy_raw)
    previous = summary(previous_raw)
    current = summary(current_raw)
    comparisons = {
        "paid_amount_mom": ratio(current["paid_amount"], previous["paid_amount"]),
        "paid_amount_yoy": ratio(current["paid_amount"], yoy["paid_amount"]),
        "orders_mom": ratio(current["orders"], previous["orders"]),
        "orders_yoy": ratio(current["orders"], yoy["orders"]),
        "quantity_mom": ratio(current["quantity"], previous["quantity"]),
        "quantity_yoy": ratio(current["quantity"], yoy["quantity"]),
        "avg_order_amount_mom": ratio(current["avg_order_amount"], previous["avg_order_amount"]),
        "avg_order_amount_yoy": ratio(current["avg_order_amount"], yoy["avg_order_amount"]),
    }

    period_rows = []
    for index, (item, values, suffix) in enumerate(
        [(yoy_raw, yoy, "去年同期"), (previous_raw, previous, "上月"), (current_raw, current, "本月")], 1
    ):
        period_rows.append({"sort_order": index, "period": f"{month_text(item['start_date'])}（{suffix}）", **values})

    daily = [
        {
            "sales_date": row["sales_date"],
            "paid_amount": float(row["paid_amount"] or 0),
            "orders": int(row["orders"] or 0),
            "quantity": float(row["quantity"] or 0),
        }
        for row in raw["daily"]
    ]
    brands_all = [
        {
            "rank": index,
            "brand": row["brand"] or "未归类",
            "paid_amount": float(row["paid_amount"] or 0),
            "orders": int(row["orders"] or 0),
            "quantity": float(row["quantity"] or 0),
        }
        for index, row in enumerate(raw["brands"], 1)
    ]
    brands = brands_all[:5]

    channel_rows = []
    product_rows = []
    customer_rows = []
    arrival_rows = []
    inventory_rows = []
    for item, suffix in zip(periods, ["去年同期", "上月", "本月"]):
        label = month_text(item["start_date"])
        total_amount = float(item["summary"]["paid_amount"] or 0)
        for key, name in [("online", "线上"), ("offline", "线下")]:
            values = item["channel_summary"][key]
            channel_rows.append({
                "period": label,
                "channel_group": name,
                "paid_amount": float(values["paid_amount"] or 0),
                "orders": int(values["orders"] or 0),
                "quantity": float(values["quantity"] or 0),
                "share": float(values["paid_amount"] or 0) / total_amount if total_amount else 0,
                "unmatched_channels": int(item["channel_summary"]["unmatched_channels"] or 0),
            })
        scopes = {row["product_type_scope"]: row for row in item["product_scopes"]}
        for key, name in [("full_size", "正装"), ("sample", "小样")]:
            values = scopes.get(key, {})
            product_rows.append({
                "period": label,
                "product_type": name,
                "paid_amount": float(values.get("paid_amount") or 0),
                "orders": int(values.get("orders") or 0),
                "quantity": float(values.get("quantity") or 0),
            })
        customers = item["customer_summary"]
        quality = item["customer_quality"]
        customer_count = int(customers["customers"] or 0)
        repeat_count = int(customers["repeat_customers"] or 0)
        quality_amount = float(quality["paid_amount"] or 0)
        customer_rows.append({
            "period": f"{label}（{suffix}）",
            "customers": customer_count,
            "repeat_customers": repeat_count,
            "repeat_rate": repeat_count / customer_count if customer_count else 0,
            "identified_amount_rate": float(quality["identified_amount"] or 0) / quality_amount if quality_amount else 0,
        })
        arrivals = item["arrivals"]
        arrival_rows.append({
            "period": f"{label}（{suffix}）",
            "net_quantity": float(arrivals["net_quantity"] or 0),
            "document_count": int(arrivals["document_count"] or 0),
            "brand_count": int(arrivals["brand_count"] or 0),
        })
        inventory = item["inventory_snapshot"]
        inventory_rows.append({
            "period": f"{label}（{suffix}）",
            "snapshot_date": inventory.get("snapshot_date"),
            "stock_quantity": float(inventory.get("stock_quantity") or 0),
            "detail_rows": int(inventory.get("detail_rows") or 0),
        })

    datasets = artifact["snapshot"]["datasets"]
    datasets["headline"] = [{**current, **comparisons}]
    datasets["periods"] = period_rows
    datasets["daily"] = daily
    datasets["brands"] = brands
    datasets["channel_structure"] = channel_rows
    datasets["product_types"] = product_rows
    datasets["customers"] = customer_rows
    datasets["arrivals"] = arrival_rows
    datasets["inventory_snapshots"] = inventory_rows

    title = f"{current_name}经营月报"
    artifact["manifest"]["title"] = title
    artifact["manifest"]["generatedAt"] = generated_at
    artifact["snapshot"]["generatedAt"] = generated_at
    blocks = block_map(artifact)
    card_descriptions = {
        "sales_amount": f"{current_name}完整自然月订单实付金额，与完整上月和去年同期比较。",
        "sales_orders": f"{current_name}完整自然月订单数，与完整上月和去年同期比较。",
        "sales_quantity": f"{current_name}完整自然月销售数量，与完整上月和去年同期比较。",
        "average_order_amount": "销售额除以订单数，仅反映该汇总口径下的平均值。",
    }
    for card in artifact["manifest"]["cards"]:
        card["description"] = card_descriptions[card["id"]]
    blocks["title"]["body"] = f"# {title}"
    blocks["executive_summary"]["body"] = (
        "## 一、经营摘要\n\n"
        f"- **{month_number}月销售额为{yi(current['paid_amount'])}。** 较{previous_name}{movement(comparisons['paid_amount_mom'])}，较{yoy_name}{movement(comparisons['paid_amount_yoy'])}。\n"
        f"- **{month_number}月订单数为{current['orders'] / 10_000:.2f}万单。** 环比{movement(comparisons['orders_mom'])}，同比{movement(comparisons['orders_yoy'])}。\n"
        f"- **{month_number}月销售数量为{current['quantity'] / 10_000:.2f}万件。** 环比{movement(comparisons['quantity_mom'])}，同比{movement(comparisons['quantity_yoy'])}。\n"
        f"- **平均订单金额为{current['avg_order_amount']:,.2f}元。** 环比{movement(comparisons['avg_order_amount_mom'])}，同比{movement(comparisons['avg_order_amount_yoy'])}。本报告只陈述汇总变化，不对原因作推断。"
    )
    blocks["scope_definition"]["body"] = (
        "## 二、报告范围与比较口径\n\n"
        f"本报告仅覆盖已经核验的经营数据。报告期为{current_raw['start_date']}至{current_raw['end_date']}；"
        f"环比基准为{previous_raw['start_date']}至{previous_raw['end_date']}；"
        f"同比基准为{yoy_raw['start_date']}至{yoy_raw['end_date']}。三个期间均为完整自然月，并使用对应的已发布ADS数据版本。"
    )
    blocks["comparison_interpretation"]["body"] = (
        "## 三、销售总体表现\n\n"
        f"{month_number}月销售额环比{movement(comparisons['paid_amount_mom'])}、同比{movement(comparisons['paid_amount_yoy'])}；"
        f"订单数环比{movement(comparisons['orders_mom'])}、同比{movement(comparisons['orders_yoy'])}；"
        f"销售数量环比{movement(comparisons['quantity_mom'])}、同比{movement(comparisons['quantity_yoy'])}。"
        "这些数字只描述汇总结果，不单独推断渠道、商品或客户结构变化的原因。"
    )
    if daily:
        ranked = sorted(daily, key=lambda row: row["paid_amount"], reverse=True)
        lowest = min(daily, key=lambda row: row["paid_amount"])
        blocks["daily_interpretation"]["body"] = (
            "## 四、月内销售趋势\n\n"
            f"每日销售额最高为{wan(ranked[0]['paid_amount'])}，出现在{ranked[0]['sales_date']}；"
            f"其次为{wan(ranked[1]['paid_amount'])}，出现在{ranked[1]['sales_date']}。"
            f"最低为{wan(lowest['paid_amount'])}，出现在{lowest['sales_date']}。报告只标记客观高低点，不自动解释原因。"
        )
    brand_total = sum(row["paid_amount"] for row in brands_all)
    brand_coverage = brand_total / current["paid_amount"] if current["paid_amount"] else 0
    brand_text = "、".join(f"{row['brand']}{wan(row['paid_amount'])}" for row in brands)
    blocks["brand_interpretation"]["body"] = (
        "## 五、品牌销售表现\n\n"
        f"已归入品牌分析表的销售额为{yi(brand_total)}，占销售总额{brand_coverage * 100:.1f}%。"
        f"销售额前五品牌为：{brand_text}。未覆盖部分保留为明确的数据缺口。"
    )
    current_channels = {row["channel_group"]: row for row in channel_rows[-2:]}
    previous_channels = {row["channel_group"]: row for row in channel_rows[-4:-2]}
    online = current_channels["线上"]
    offline = current_channels["线下"]
    blocks["channel_interpretation"]["body"] = (
        "## 六、线上与线下销售结构\n\n"
        f"线上销售额为{wan(online['paid_amount'])}，占总销售额{online['share'] * 100:.1f}%；"
        f"线下销售额为{yi(offline['paid_amount'])}，占{offline['share'] * 100:.1f}%。"
        f"与上月相比，线上{movement(ratio(online['paid_amount'], previous_channels['线上']['paid_amount']))}，"
        f"线下{movement(ratio(offline['paid_amount'], previous_channels['线下']['paid_amount']))}。"
        f"去年同期有{yoy_raw['channel_summary']['unmatched_channels']}个渠道未匹配当前配置，渠道同比不用于结构结论。"
    )
    current_products = {row["product_type"]: row for row in product_rows[-2:]}
    previous_products = {row["product_type"]: row for row in product_rows[-4:-2]}
    yoy_products = {row["product_type"]: row for row in product_rows[:2]}
    classified_amount = sum(row["paid_amount"] for row in current_products.values())
    product_coverage = classified_amount / current["paid_amount"] if current["paid_amount"] else 0
    blocks["product_type_interpretation"]["body"] = (
        "## 七、正装与小样销售结构\n\n"
        f"正装销售额为{wan(current_products['正装']['paid_amount'])}，环比{movement(ratio(current_products['正装']['paid_amount'], previous_products['正装']['paid_amount']))}、"
        f"同比{movement(ratio(current_products['正装']['paid_amount'], yoy_products['正装']['paid_amount']))}；"
        f"小样销售额为{wan(current_products['小样']['paid_amount'])}，环比{movement(ratio(current_products['小样']['paid_amount'], previous_products['小样']['paid_amount']))}、"
        f"同比{movement(ratio(current_products['小样']['paid_amount'], yoy_products['小样']['paid_amount']))}。"
        f"两类合计覆盖销售总额{product_coverage * 100:.1f}%。"
    )
    current_customer = customer_rows[-1]
    previous_customer = customer_rows[-2]
    identified_sales_share = float(current_raw["customer_summary"]["paid_amount"] or 0) / current["paid_amount"] if current["paid_amount"] else 0
    blocks["customer_interpretation"]["body"] = (
        "## 八、客户情况\n\n"
        f"可识别客户为{current_customer['customers']:,}个，较上月{movement(ratio(current_customer['customers'], previous_customer['customers']))}；"
        f"月内订单数不少于2单的客户为{current_customer['repeat_customers']:,}个，较上月{movement(ratio(current_customer['repeat_customers'], previous_customer['repeat_customers']))}，"
        f"占可识别客户{current_customer['repeat_rate'] * 100:.1f}%。客户识别金额占客户分析明细金额{current_customer['identified_amount_rate'] * 100:.1f}%，"
        f"占销售总额{identified_sales_share * 100:.1f}%；本节不代表全部客户。"
    )
    current_arrival, previous_arrival, yoy_arrival = arrival_rows[-1], arrival_rows[-2], arrival_rows[0]
    blocks["arrival_interpretation"]["body"] = (
        "## 九、月度到货情况\n\n"
        f"净到货数量为{current_arrival['net_quantity'] / 10_000:.2f}万件，"
        f"环比{movement(ratio(current_arrival['net_quantity'], previous_arrival['net_quantity']))}、"
        f"同比{movement(ratio(current_arrival['net_quantity'], yoy_arrival['net_quantity']))}；"
        f"共有{current_arrival['document_count']:,}张入库单、{current_arrival['brand_count']:,}个到货品牌。净到货数量包含红冲和负数记录。\n\n"
        "**到货成本：暂不可用。** 当前源数据中的入库成本字段尚未完成业务口径核准，本报告不展示成本金额及其同比、环比。"
    )
    current_inventory, previous_inventory, yoy_inventory = inventory_rows[-1], inventory_rows[-2], inventory_rows[0]
    blocks["inventory_interpretation"]["body"] = (
        "## 十、月末库存情况\n\n"
        f"月末成功快照的库存数量为{current_inventory['stock_quantity'] / 10_000:.2f}万件，"
        f"较上月{movement(ratio(current_inventory['stock_quantity'], previous_inventory['stock_quantity']))}，"
        f"较去年同期{movement(ratio(current_inventory['stock_quantity'], yoy_inventory['stock_quantity']))}。"
        "历史快照表提供的是库存量，本节不将其表述为可用库存。"
    )
    blocks["known_limits"]["body"] = (
        "## 十一、数据口径与限制\n\n"
        f"- 品牌分析覆盖销售总额{brand_coverage * 100:.1f}%，正装与小样分类覆盖{product_coverage * 100:.1f}%；未覆盖部分均保留为明确缺口。\n"
        f"- 去年同期有{yoy_raw['channel_summary']['unmatched_channels']}个渠道未匹配当前渠道配置，渠道同比不用于结构结论。\n"
        "- 客户指标只覆盖具有客户标识的销售明细，月内复购不等同于跨月复购。\n"
        "- 到货成本依赖源入库成本字段，目前业务口径尚未核准，因此不展示金额及同比、环比。\n"
        "- 月末历史快照统计库存量，不等同于可用库存；本报告未展示库存金额。\n"
        "- 同比仅在销售ADS覆盖去年同期完整自然月时计算。"
    )

    charts = chart_map(artifact)
    charts["period_sales_comparison"]["title"] = f"{yoy_name}、{previous_name}和{current_name}销售额"
    charts["daily_sales_trend"]["title"] = f"{current_name}每日销售额"
    charts["daily_sales_trend"]["subtitle"] = f"完整自然月{len(daily)}个日数据点；单位：元"
    charts["brand_sales_top5"]["title"] = f"{current_name}品牌销售额前五"
    charts["brand_sales_top5"]["subtitle"] = "仅统计已归入品牌分析表的金额；单位：元"
    charts["channel_structure"]["subtitle"] = f"{yoy_name}、{previous_name}和{current_name}；单位：元"
    charts["product_type_structure"]["subtitle"] = f"{yoy_name}、{previous_name}和{current_name}；单位：元"

    sources = source_map(artifact)
    for source in sources.values():
        source["query"]["executed_at"] = generated_at
    sources["sales_daily"]["query"]["description"] = f"读取{current_name}每日销售额、订单数和销售数量。"
    sources["sales_brand"]["query"]["description"] = f"读取{current_name}已归因品牌销售额，并按金额排序。"
    for source in sources.values():
        filters = source["query"].get("filters", [])
        source["query"]["filters"] = [
            item.replace("REPORT_START至REPORT_END", f"{current_raw['start_date']}至{current_raw['end_date']}")
                .replace("PREVIOUS_START至PREVIOUS_END", f"{previous_raw['start_date']}至{previous_raw['end_date']}")
                .replace("YEAR_AGO_START至YEAR_AGO_END", f"{yoy_raw['start_date']}至{yoy_raw['end_date']}")
                .replace("SALES_DATA_VERSION", raw["sales_batch"]["data_version"])
                .replace("INVENTORY_DATA_VERSION", raw["inventory_batch"]["data_version"])
            for item in filters
        ]

    artifact["package_info"]["root"] = f"monthly-operating-report-{month}"
    artifact["package_info"]["manifestPath"] = f"monthly_operating_report_{month.replace('-', '_')}_artifact.json"
    artifact["package_info"]["snapshotPath"] = artifact["package_info"]["manifestPath"]
    return artifact


def render_portable_html(artifact: dict) -> str:
    shell = HTML_SHELL.read_text(encoding="utf-8")
    payload = json.dumps(artifact, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded = base64.b64encode(gzip.compress(payload, mtime=0)).decode("ascii")
    wrapped = "\n".join(encoded[index:index + 76] for index in range(0, len(encoded), 76))
    pattern = re.compile(
        r'(<template id="data-analytics-portable-artifact-payload-source"[^>]*>).*?(</template>)',
        re.DOTALL,
    )
    rendered, count = pattern.subn(lambda match: f"{match.group(1)}\n{wrapped}\n{match.group(2)}", shell, count=1)
    if count != 1:
        raise ValueError("月报HTML模板缺少 artifact payload 容器")
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description="按月份生成固定结构的经营月报。")
    parser.add_argument("--month", required=True, help="报告月份，格式 YYYY-MM。")
    parser.add_argument("--artifact-only", action="store_true", help="只生成 artifact JSON，不渲染 HTML。")
    args = parser.parse_args()
    raw = load_raw(args.month)
    validate_raw(raw)
    artifact = build_artifact(args.month, raw)
    stem = args.month.replace("-", "_")
    artifact_path = OUTPUT_DIR / f"monthly_operating_report_{stem}_artifact.json"
    html_path = OUTPUT_DIR / f"monthly_operating_report_{stem}.html"
    artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.artifact_only:
        html_path.write_text(render_portable_html(artifact), encoding="utf-8")
    print(json.dumps({"artifact": str(artifact_path), "html": None if args.artifact_only else str(html_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
