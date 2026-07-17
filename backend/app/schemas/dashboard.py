from pydantic import BaseModel


class MetricCard(BaseModel):
    title: str
    value: int | float | str
    unit: str | None = None
    trend: float | None = None


class ChartPoint(BaseModel):
    label: str
    value: int | float


class DashboardOverview(BaseModel):
    metrics: list[MetricCard]
    sales_trend: list[ChartPoint]
    category_share: list[ChartPoint]
    recent_events: list[str]
