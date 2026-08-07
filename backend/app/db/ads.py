from collections.abc import Generator

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.performance import register_engine_performance


def _mysql_connect_args(url: str) -> dict:
    if not url.startswith("mysql"):
        return {}
    return {
        "charset": "utf8mb4",
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 60,
    }


def ensure_separate_ads_database(ods_url: str, ads_url: str) -> None:
    if not ods_url or not ads_url:
        return

    ods = make_url(ods_url)
    ads = make_url(ads_url)
    same_server = (
        ods.get_backend_name() == ads.get_backend_name()
        and (ods.host or "").lower() == (ads.host or "").lower()
        and (ods.port or 3306) == (ads.port or 3306)
    )
    if same_server and (ods.database or "").lower() == (ads.database or "").lower():
        # 允许相同数据库用于开发环境
        import warnings
        warnings.warn("ADS_DATABASE_URL is the same as ODS_DATABASE_URL; this is allowed for development")
        return


def create_ads_engine(url: str) -> Engine:
    ensure_separate_ads_database(settings.ODS_DATABASE_URL, url)
    engine_options: dict = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    if not url.startswith("sqlite"):
        engine_options.update(
            pool_size=settings.ADS_POOL_SIZE,
            max_overflow=settings.ADS_MAX_OVERFLOW,
        )
    return create_engine(
        url,
        connect_args=_mysql_connect_args(url),
        **engine_options,
    )


if settings.ADS_DATABASE_URL:
    ads_engine = create_ads_engine(settings.ADS_DATABASE_URL)
    AdsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ads_engine)
else:
    ads_engine = None
    AdsSessionLocal = None

if settings.ADS_BUILD_DATABASE_URL:
    ads_build_engine = create_ads_engine(settings.ADS_BUILD_DATABASE_URL)
    AdsBuildSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ads_build_engine)
else:
    ads_build_engine = None
    AdsBuildSessionLocal = None

register_engine_performance(ads_engine, "ads")


def require_ads_engine() -> Engine:
    if ads_engine is None:
        raise RuntimeError("ADS_DATABASE_URL is not configured")
    return ads_engine


def require_ads_session_factory() -> sessionmaker[Session]:
    if AdsSessionLocal is None:
        raise RuntimeError("ADS_DATABASE_URL is not configured")
    return AdsSessionLocal


def require_ads_build_session_factory() -> sessionmaker[Session]:
    if AdsBuildSessionLocal is None:
        raise RuntimeError("ADS_BUILD_DATABASE_URL is not configured")
    return AdsBuildSessionLocal


def initialize_ads_schema() -> None:
    from app.models.ads import AdsBase

    if ads_build_engine is None:
        raise RuntimeError("ADS_BUILD_DATABASE_URL is not configured")
    AdsBase.metadata.create_all(bind=ads_build_engine)


def get_ads_db() -> Generator[Session, None, None]:
    if AdsSessionLocal is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": 503,
                "message": "ADS database is not configured",
                "data": None,
            },
        )

    db = AdsSessionLocal()
    try:
        yield db
    finally:
        db.close()
