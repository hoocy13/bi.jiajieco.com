import json
import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routers.reports import (
    delete_monthly_report_version,
    download_monthly_report_pdf,
    download_monthly_report_version,
    get_monthly_report,
    list_monthly_report_versions,
    list_monthly_reports,
    publish_monthly_report_version,
)
from app.db.session import Base
from app.models.monthly_report import MonthlyOperatingReport


class MonthlyReportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        for revision in (1, 2):
            self.db.add(MonthlyOperatingReport(
                report_month="2026-08",
                revision=revision,
                status="published",
                sales_data_version="sales-v1",
                inventory_data_version="inventory-v1",
                artifact_json=json.dumps({"manifest": {"title": f"月报V{revision}"}}),
                html_content=f"<html>V{revision}</html>",
                pdf_content=f"%PDF-V{revision}".encode(),
                generated_at=datetime(2026, 9, 9, 8, revision),
            ))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def test_list_returns_one_latest_entry_per_month(self) -> None:
        result = list_monthly_reports(current_user=object(), db=self.db)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["revision"], 2)

    def test_get_returns_latest_published_snapshot(self) -> None:
        result = get_monthly_report("2026-08", current_user=object(), db=self.db)
        self.assertEqual(result["data"]["revision"], 2)
        self.assertEqual(result["data"]["artifact"]["manifest"]["title"], "月报V2")

    def test_download_uses_same_latest_snapshot(self) -> None:
        response = download_monthly_report_pdf("2026-08", current_user=object(), db=self.db)
        self.assertEqual(response.body, b"%PDF-V2")
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn("monthly_operating_report_2026_08.pdf", response.headers["content-disposition"])

    def test_management_lists_versions_and_can_publish_draft(self) -> None:
        draft = MonthlyOperatingReport(
            report_month="2026-09",
            revision=1,
            status="draft",
            sales_data_version="sales-v2",
            inventory_data_version="inventory-v2",
            artifact_json="{}",
            html_content="<html></html>",
            pdf_content=b"%PDF-draft",
            generated_at=datetime(2026, 10, 1, 8, 0),
        )
        self.db.add(draft)
        self.db.commit()
        rows = list_monthly_report_versions(db=self.db)["data"]
        self.assertEqual(rows[0]["status"], "draft")
        result = publish_monthly_report_version("2026-09", 1, db=self.db)
        self.assertEqual(result["data"]["status"], "published")

    def test_management_can_download_exact_version(self) -> None:
        response = download_monthly_report_version("2026-08", 1, db=self.db)
        self.assertEqual(response.body, b"%PDF-V1")
        self.assertIn("monthly_operating_report_2026_08_v1.pdf", response.headers["content-disposition"])

    def test_management_can_delete_exact_version(self) -> None:
        result = delete_monthly_report_version("2026-08", 1, db=self.db)
        self.assertTrue(result["data"]["deleted"])
        remaining = list_monthly_report_versions(db=self.db)["data"]
        self.assertEqual([item["revision"] for item in remaining], [2])


if __name__ == "__main__":
    unittest.main()
