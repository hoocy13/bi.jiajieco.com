from collections.abc import Generator

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.performance import register_engine_performance


def create_ods_engine(database_url: str, read_timeout: int = 30) -> Engine:
    engine = create_engine(
        database_url,
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": read_timeout,
            "write_timeout": read_timeout,
        },
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    register_engine_performance(engine, "ods")
    return engine


if settings.ODS_DATABASE_URL:
    ods_engine = create_ods_engine(settings.ODS_DATABASE_URL)
    OdsSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=ods_engine)
else:
    ods_engine = None
    OdsSessionLocal = None


def get_ods_db() -> Generator[Session, None, None]:
    if OdsSessionLocal is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": 503,
                "message": "ODS database is not configured",
                "data": None,
            },
        )

    db = OdsSessionLocal()
    try:
        yield db
    finally:
        db.close()
