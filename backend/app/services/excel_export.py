from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

import xlsxwriter


@dataclass(frozen=True)
class ExportColumn:
    key: str
    label: str
    kind: str = "text"
    width: int = 16


def _display(value: object) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return "、".join(str(item) for item in value) or "全部"
    return str(value)


def create_excel_export(
    *,
    title: str,
    columns: tuple[ExportColumn, ...],
    rows: Iterable[dict],
    filters: dict[str, object],
    notes: tuple[str, ...],
) -> Path:
    temp = NamedTemporaryFile(prefix="bi-export-", suffix=".xlsx", delete=False)
    temp.close()
    path = Path(temp.name)
    workbook = xlsxwriter.Workbook(
        str(path),
        {
            "constant_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    header_format = workbook.add_format(
        {"bold": True, "font_color": "#FFFFFF", "bg_color": "#3448C5", "border": 0, "align": "center"}
    )
    text_format = workbook.add_format({"num_format": "@"})
    integer_format = workbook.add_format({"num_format": "#,##0"})
    number_format = workbook.add_format({"num_format": "#,##0.00"})
    percent_format = workbook.add_format({"num_format": "0.0%"})
    date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
    label_format = workbook.add_format({"bold": True, "font_color": "#344054", "bg_color": "#F2F4F7"})
    try:
        detail = workbook.add_worksheet("数据明细")
        detail.freeze_panes(1, 0)
        detail.autofilter(0, 0, 0, max(0, len(columns) - 1))
        for column_index, column in enumerate(columns):
            detail.write(0, column_index, column.label, header_format)
            detail.set_column(column_index, column_index, column.width)
        for row_index, row in enumerate(rows, start=1):
            for column_index, column in enumerate(columns):
                value = row.get(column.key)
                if value is None:
                    detail.write_blank(row_index, column_index, None)
                elif column.kind == "integer":
                    detail.write_number(row_index, column_index, float(value), integer_format)
                elif column.kind == "number":
                    detail.write_number(row_index, column_index, float(value), number_format)
                elif column.kind == "percent":
                    detail.write_number(row_index, column_index, float(value) / 100, percent_format)
                elif column.kind == "date":
                    try:
                        parsed = value if isinstance(value, (date, datetime)) else datetime.fromisoformat(str(value)[:10])
                        detail.write_datetime(row_index, column_index, parsed, date_format)
                    except (TypeError, ValueError):
                        detail.write_string(row_index, column_index, _display(value), text_format)
                else:
                    detail.write_string(row_index, column_index, _display(value), text_format)

        criteria = workbook.add_worksheet("筛选条件")
        criteria.set_column(0, 0, 22)
        criteria.set_column(1, 1, 54)
        criteria.write(0, 0, "导出内容", label_format)
        criteria.write_string(0, 1, title, text_format)
        criteria.write(1, 0, "导出时间", label_format)
        criteria.write_string(1, 1, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text_format)
        for index, (label, value) in enumerate(filters.items(), start=2):
            criteria.write(index, 0, label, label_format)
            criteria.write_string(index, 1, _display(value), text_format)

        basis = workbook.add_worksheet("口径说明")
        basis.set_column(0, 0, 100)
        basis.write(0, 0, f"{title}导出说明", label_format)
        for index, note in enumerate(notes, start=1):
            basis.write_string(index, 0, note, text_format)
        workbook.close()
    except Exception:
        workbook.close()
        path.unlink(missing_ok=True)
        raise
    return path
