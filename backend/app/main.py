from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import ai_decisions, auth, dashboard, inventory, model_settings, rag, sales, text_to_sql, users
from app.core.config import settings
from app.core.performance import performance_middleware
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "Server-Timing",
            "X-Request-ID",
            "X-Response-Time-Ms",
            "X-DB-Query-Count",
            "X-DB-Time-Ms",
            "X-DB-Slow-Query-Count",
            "X-ODS-Query-Count",
            "X-ODS-Time-Ms",
            "X-ADS-Query-Count",
            "X-ADS-Time-Ms",
            "X-BI-Query-Mode",
            "X-BI-Response-Source",
            "X-BI-Dual-Status",
        ],
    )
    app.middleware("http")(performance_middleware)

    @app.get("/")
    def root() -> dict:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "name": settings.PROJECT_NAME,
                "docs": "/docs",
                "api_prefix": settings.API_PREFIX,
            },
        }

    app.include_router(auth.router, prefix=settings.API_PREFIX)
    app.include_router(dashboard.router, prefix=settings.API_PREFIX)
    app.include_router(inventory.router, prefix=settings.API_PREFIX)
    app.include_router(sales.router, prefix=settings.API_PREFIX)
    app.include_router(text_to_sql.router, prefix=settings.API_PREFIX)
    app.include_router(users.router, prefix=settings.API_PREFIX)
    app.include_router(model_settings.router, prefix=settings.API_PREFIX)
    app.include_router(ai_decisions.router, prefix=settings.API_PREFIX)
    app.include_router(rag.router, prefix=settings.API_PREFIX)
    return app


app = create_app()
