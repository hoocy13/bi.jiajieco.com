from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

from app.db.init_db import init_db  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models.monthly_report import MonthlyOperatingReport  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="将已生成的经营月报保存为只读发布快照。")
    parser.add_argument("--month", required=True, help="报告月份，格式 YYYY-MM。")
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()
    stem = args.month.replace("-", "_")
    artifact_path = PROJECT_ROOT / "outputs" / f"monthly_operating_report_{stem}_artifact.json"
    html_path = PROJECT_ROOT / "outputs" / f"monthly_operating_report_{stem}.html"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    sources = {item["id"]: item for item in artifact["manifest"]["sources"]}
    sales_filters = sources["sales_monthly"]["query"].get("filters", [])
    inventory_filters = sources["inventory_arrival"]["query"].get("filters", [])
    sales_version = next((item.split("=", 1)[1] for item in sales_filters if item.startswith("data_version=")), "")
    inventory_version = next((item.split("=", 1)[1] for item in inventory_filters if item.startswith("data_version=")), "")
    if not sales_version or not inventory_version:
        raise ValueError("报告缺少销售或库存数据版本，不能发布。")
    generated_at = datetime.fromisoformat(artifact["manifest"]["generatedAt"]).replace(tzinfo=None)
    init_db()
    db = SessionLocal()
    try:
        row = (
            db.query(MonthlyOperatingReport)
            .filter_by(report_month=args.month, revision=args.revision)
            .first()
        )
        if row is None:
            row = MonthlyOperatingReport(report_month=args.month, revision=args.revision)
            db.add(row)
        row.status = "published"
        row.sales_data_version = sales_version
        row.inventory_data_version = inventory_version
        row.artifact_json = json.dumps(artifact, ensure_ascii=False)
        row.html_content = html_path.read_text(encoding="utf-8")
        row.generated_at = generated_at
        db.commit()
        print(json.dumps({"month": args.month, "revision": args.revision, "status": row.status}, ensure_ascii=False))
    finally:
        db.close()


if __name__ == "__main__":
    main()
