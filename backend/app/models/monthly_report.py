from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class MonthlyOperatingReport(Base):
    __tablename__ = "monthly_operating_reports"
    __table_args__ = (UniqueConstraint("report_month", "revision", name="uq_monthly_report_revision"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_month: Mapped[str] = mapped_column(String(7), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="published", index=True)
    sales_data_version: Mapped[str] = mapped_column(String(160))
    inventory_data_version: Mapped[str] = mapped_column(String(160))
    artifact_json: Mapped[str] = mapped_column(Text)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
