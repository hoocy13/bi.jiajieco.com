"""Freeze extra operating analysis as a new local monthly report revision."""
import argparse
import json
from datetime import datetime, timezone
from sqlalchemy import func
from app.db.session import SessionLocal
from app.db.ads import AdsSessionLocal
from app.db.ods import OdsSessionLocal
from app.models.monthly_report import MonthlyOperatingReport
from app.services.monthly_operating_analysis import build_operating_analysis


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--month',required=True)
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args()
    with SessionLocal() as db, AdsSessionLocal() as ads, OdsSessionLocal() as ods:
        original=db.query(MonthlyOperatingReport).filter_by(report_month=args.month,status='published').order_by(MonthlyOperatingReport.revision.desc()).first()
        if original is None:
            raise ValueError('缺少已发布月报')
        artifact=json.loads(original.artifact_json)
        analysis=build_operating_analysis(ads,ods,artifact,args.month,original.sales_data_version)
        artifact['snapshot']['datasets']['operating_analysis']=analysis
        revision=(db.query(func.max(MonthlyOperatingReport.revision)).filter_by(report_month=args.month).scalar() or 0)+1
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        row=MonthlyOperatingReport(report_month=args.month,revision=revision,status='published' if args.publish else 'draft',
            sales_data_version=original.sales_data_version,inventory_data_version=original.inventory_data_version,
            artifact_json=json.dumps(artifact,ensure_ascii=False),html_content=original.html_content,
            generated_at=now,published_at=now if args.publish else None)
        db.add(row);db.commit()
        print(json.dumps(dict(revision=revision,status=row.status,channels=len(analysis['drivers']),brands=len(analysis['brands']),
                              headline_gap=analysis['headline_gap'],inventory=analysis['inventory']),ensure_ascii=False))

if __name__=='__main__':main()
