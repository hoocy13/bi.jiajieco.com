from collections.abc import Generator

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.performance import register_engine_performance
from app.db.ads import (
    create_ads_engine,
    get_ads_db,
    require_ads_build_session_factory,
)


profit_engine = (
    create_ads_engine(settings.SALES_PROFIT_DATABASE_URL)
    if settings.SALES_PROFIT_DATABASE_URL else None
)
ProfitSessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=profit_engine)
    if profit_engine is not None else None
)
profit_build_engine = (
    create_ads_engine(
        settings.SALES_PROFIT_BUILD_DATABASE_URL,
        read_timeout=settings.ADS_BUILD_READ_TIMEOUT_SECONDS,
    )
    if settings.SALES_PROFIT_BUILD_DATABASE_URL else None
)
ProfitBuildSessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, bind=profit_build_engine)
    if profit_build_engine is not None else None
)
register_engine_performance(profit_engine, "ads")


def get_sales_profit_db() -> Generator[Session, None, None]:
    if ProfitSessionLocal is None:
        yield from get_ads_db()
        return
    with ProfitSessionLocal() as db:
        yield db


def get_monthly_profit_db():
    if settings.BI_QUERY_SOURCE != 'ads':
        yield None
        return
    yield from get_sales_profit_db()


def require_sales_profit_build_session_factory() -> sessionmaker[Session]:
    if ProfitBuildSessionLocal is not None:
        return ProfitBuildSessionLocal
    return require_ads_build_session_factory()


def initialize_sales_profit_schema() -> None:
    from app.models.ads import AdsPublishBatch, AdsSalesProfitDaily

    engine = require_sales_profit_build_session_factory().kw["bind"]
    AdsPublishBatch.__table__.create(bind=engine, checkfirst=True)
    AdsSalesProfitDaily.__table__.create(bind=engine, checkfirst=True)
