from pathlib import Path
from zipfile import ZipFile

from app.services.excel_export import ExportColumn, create_excel_export


def test_excel_export_has_expected_sheets_and_keeps_identifiers_as_text() -> None:
    path = create_excel_export(
        title="测试导出",
        columns=(
            ExportColumn("code", "编号"),
            ExportColumn("amount", "金额", "number"),
            ExportColumn("ratio", "比例", "percent"),
        ),
        rows=[{"code": "=1+1", "amount": 12.5, "ratio": 75}],
        filters={"品牌": "资生堂"},
        notes=("测试口径",),
    )
    try:
        with ZipFile(path) as archive:
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            detail_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert "数据明细" in workbook_xml
        assert "筛选条件" in workbook_xml
        assert "口径说明" in workbook_xml
        assert "=1+1" in detail_xml
        assert "<f>" not in detail_xml
    finally:
        Path(path).unlink(missing_ok=True)
