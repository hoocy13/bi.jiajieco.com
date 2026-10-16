"""Add frozen channel detail to a new local report revision without changing existing totals."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

BACKEND_ROOT = Path(os.environ.get("BI_BACKEND_ROOT", Path(__file__).resolve().parents[2]))
PROJECT_ROOT = Path(os.environ.get("BI_PROJECT_ROOT", BACKEND_ROOT.parent))
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "outputs"))
os.chdir(BACKEND_ROOT)

from app.db.session import SessionLocal
from app.models.monthly_report import MonthlyOperatingReport
from generate_monthly_operating_report import add_channel_analysis, month_text, render_portable_html


def validate_snapshot(artifact: dict, raw: dict, version: str) -> None:
    if raw["sales_batch"]["data_version"] != version:
        raise ValueError("渠道数据版本与月报不一致")
    datasets = artifact["snapshot"]["datasets"]
    for period in raw["periods"]:
        label = month_text(period["start_date"])
        old = next(row for row in datasets["periods"] if row["period"].startswith(f"{label}（"))
        for field in ("paid_amount", "orders", "quantity"):
            total = sum((Decimal(str(row[field])) for row in period["channels"]), Decimal("0"))
            if abs(total - Decimal(str(old[field]))) > Decimal("0.01"):
                raise ValueError(f"{label}渠道{field}与原月报不一致")
        for group in ("线上", "线下"):
            old_group = next(row for row in datasets["channel_structure"] if row["period"] == label and row["channel_group"] == group)
            for field in ("paid_amount", "orders", "quantity"):
                total = sum((Decimal(str(row[field])) for row in period["channels"] if row["channel_group"] == group), Decimal("0"))
                if abs(total - Decimal(str(old_group[field]))) > Decimal("0.01"):
                    raise ValueError(f"{label}{group}渠道{field}与原月报不一致")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True)
    parser.add_argument("--raw-file", required=True, type=Path)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    raw = json.loads(args.raw_file.read_text(encoding="utf-8-sig"))
    if raw["periods"][-1]["start_date"][:7] != args.month:
        raise ValueError("渠道数据月份与报告月份不一致")
    with SessionLocal() as db:
        original = db.query(MonthlyOperatingReport).filter_by(report_month=args.month, status="published").order_by(MonthlyOperatingReport.revision.desc()).first()
        if original is None:
            raise ValueError("该月份尚无已发布月报")
        artifact = json.loads(original.artifact_json)
        validate_snapshot(artifact, raw, original.sales_data_version)
        add_channel_analysis(artifact, raw)
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        artifact["manifest"]["generatedAt"] = now.isoformat(timespec="seconds")
        artifact["snapshot"]["generatedAt"] = artifact["manifest"]["generatedAt"]
        source = next(item for item in artifact["manifest"]["sources"] if item["id"] == "sales_channel")
        source["query"]["executed_at"] = artifact["manifest"]["generatedAt"]
        source["query"]["description"] = "按月报原销售版本读取具体渠道，渠道分类与平台在补充时冻结。"
        latest = db.query(MonthlyOperatingReport).filter_by(report_month=args.month).order_by(MonthlyOperatingReport.revision.desc()).first()
        revision = latest.revision + 1
        row = MonthlyOperatingReport(
            report_month=args.month, revision=revision, status="published" if args.publish else "draft",
            sales_data_version=original.sales_data_version, inventory_data_version=original.inventory_data_version,
            artifact_json=json.dumps(artifact, ensure_ascii=False), html_content=render_portable_html(artifact),
            generated_at=now.replace(tzinfo=None), published_at=datetime.now(timezone.utc).replace(tzinfo=None) if args.publish else None,
        )
        db.add(row)
        db.commit()
        print(json.dumps({"month": args.month, "revision": revision, "status": row.status, "channels": len(artifact["snapshot"]["datasets"]["channel_sales"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
