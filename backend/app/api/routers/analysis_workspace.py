import logging

from fastapi import APIRouter, HTTPException, Response

from app.db.ads import AdsSessionLocal
from app.schemas.common import ok
from app.services.analysis_workspace import load_sales_workspace
from app.services.sales_ads import AdsDataUnavailable


router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger("uvicorn.error")


@router.get("/analysis-workspace")
def get_analysis_workspace(response: Response) -> dict:
    if AdsSessionLocal is None:
        raise HTTPException(status_code=503, detail="ADS database is not configured")
    try:
        with AdsSessionLocal() as ads_db:
            data = load_sales_workspace(ads_db)
    except AdsDataUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("analysis_workspace status=error error_type=%s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="分析数据暂时不可用") from exc
    response.headers["X-BI-Query-Mode"] = "ads"
    response.headers["X-BI-Response-Source"] = "ads"
    return ok(data)
