import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.deps import require_permission
from app.db.session import get_db
from app.models.monthly_report import MonthlyOperatingReport
from app.models.user import User
from app.schemas.common import ok


router = APIRouter(prefix="/reports", tags=["reports"])
PROJECT_ROOT = Path(os.environ.get("BI_PROJECT_ROOT", Path(__file__).resolve().parents[4]))


class GenerateMonthlyReportRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @field_validator("month")
    @classmethod
    def validate_completed_month(cls, value: str) -> str:
        if datetime.strptime(value, "%Y-%m").date().replace(day=28) >= datetime.now().date().replace(day=1):
            raise ValueError("只能生成已经结束的完整月份")
        return value


def latest_published(db: Session, report_month: str) -> MonthlyOperatingReport | None:
    return (
        db.query(MonthlyOperatingReport)
        .filter(
            MonthlyOperatingReport.report_month == report_month,
            MonthlyOperatingReport.status == "published",
        )
        .order_by(MonthlyOperatingReport.revision.desc())
        .first()
    )


@router.get("/monthly")
def list_monthly_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.query(MonthlyOperatingReport)
        .filter(MonthlyOperatingReport.status == "published")
        .order_by(MonthlyOperatingReport.report_month.desc(), MonthlyOperatingReport.revision.desc())
        .all()
    )
    seen: set[str] = set()
    items = []
    for row in rows:
        if row.report_month in seen:
            continue
        seen.add(row.report_month)
        items.append({
            "month": row.report_month,
            "revision": row.revision,
            "generated_at": row.generated_at,
            "published_at": row.published_at,
        })
    return ok(items)


@router.get("/monthly/{report_month}")
def get_monthly_report(
    report_month: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = latest_published(db, report_month)
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "该月份尚未发布经营月报", "data": None})
    return ok({
        "month": row.report_month,
        "revision": row.revision,
        "status": row.status,
        "sales_data_version": row.sales_data_version,
        "inventory_data_version": row.inventory_data_version,
        "generated_at": row.generated_at,
        "published_at": row.published_at,
        "artifact": json.loads(row.artifact_json),
    })


@router.get("/monthly-management", dependencies=[Depends(require_permission("report.monthly.manage"))])
def list_monthly_report_versions(db: Session = Depends(get_db)) -> dict:
    rows = db.query(MonthlyOperatingReport).order_by(
        MonthlyOperatingReport.report_month.desc(),
        MonthlyOperatingReport.revision.desc(),
    ).all()
    return ok([{
        "month": row.report_month,
        "revision": row.revision,
        "status": row.status,
        "generated_at": row.generated_at,
        "published_at": row.published_at,
        "sales_data_version": row.sales_data_version,
        "inventory_data_version": row.inventory_data_version,
    } for row in rows])


@router.post("/monthly-management/generate", dependencies=[Depends(require_permission("report.monthly.manage"))])
def generate_monthly_report_draft(payload: GenerateMonthlyReportRequest, db: Session = Depends(get_db)) -> dict:
    generator = PROJECT_ROOT / "outputs" / "generate_monthly_operating_report.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.run(
            [sys.executable, str(generator), "--month", payload.month],
            cwd=PROJECT_ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
    except subprocess.CalledProcessError as exc:
        message = (exc.stderr or exc.stdout or "月报生成失败").strip().splitlines()[-1]
        raise HTTPException(status_code=422, detail={"code": 422, "message": message, "data": None}) from exc
    stem = payload.month.replace("-", "_")
    artifact_path = PROJECT_ROOT / "outputs" / f"monthly_operating_report_{stem}_artifact.json"
    html_path = PROJECT_ROOT / "outputs" / f"monthly_operating_report_{stem}.html"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8")
    sources = {item["id"]: item for item in artifact["manifest"]["sources"]}
    sales_version = next(item.split("=", 1)[1] for item in sources["sales_monthly"]["query"]["filters"] if item.startswith("data_version="))
    inventory_version = next(item.split("=", 1)[1] for item in sources["inventory_arrival"]["query"]["filters"] if item.startswith("data_version="))
    revision = int(db.query(func.max(MonthlyOperatingReport.revision)).filter(MonthlyOperatingReport.report_month == payload.month).scalar() or 0) + 1
    row = MonthlyOperatingReport(
        report_month=payload.month,
        revision=revision,
        status="draft",
        sales_data_version=sales_version,
        inventory_data_version=inventory_version,
        artifact_json=json.dumps(artifact, ensure_ascii=False),
        html_content=html,
        generated_at=datetime.fromisoformat(artifact["manifest"]["generatedAt"]).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return ok({"month": row.report_month, "revision": row.revision, "status": row.status})


@router.post("/monthly-management/{report_month}/{revision}/publish", dependencies=[Depends(require_permission("report.monthly.manage"))])
def publish_monthly_report_version(report_month: str, revision: int, db: Session = Depends(get_db)) -> dict:
    row = db.query(MonthlyOperatingReport).filter_by(report_month=report_month, revision=revision).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "月报版本不存在", "data": None})
    row.status = "published"
    row.published_at = datetime.utcnow()
    db.commit()
    return ok({"month": row.report_month, "revision": row.revision, "status": row.status})


@router.delete("/monthly-management/{report_month}/{revision}", dependencies=[Depends(require_permission("report.monthly.manage"))])
def delete_monthly_report_version(report_month: str, revision: int, db: Session = Depends(get_db)) -> dict:
    row = db.query(MonthlyOperatingReport).filter_by(report_month=report_month, revision=revision).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": 404, "message": "月报版本不存在", "data": None})
    db.delete(row)
    db.commit()
    return ok({"month": report_month, "revision": revision, "deleted": True})
