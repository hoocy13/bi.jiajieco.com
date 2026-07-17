from collections.abc import Generator

from fastapi import HTTPException, status
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


if settings.ODS_DATABASE_URL:
    ods_engine = create_engine(
        settings.ODS_DATABASE_URL,
        connect_args={
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
        },
        pool_pre_ping=True,
        pool_recycle=1800,
    )
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
