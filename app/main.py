from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.redis import close_redis, get_redis
from app.db.session import dispose_engine
from app.routers import auth, drivers, orders, uploads, users, ws

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging("DEBUG" if settings.DEBUG else "INFO")
    # Warm up Redis connection
    try:
        await get_redis().ping()
    except Exception:  # noqa: BLE001
        logger.warning("Redis ping failed at startup")
    logger.info("%s starting (env=%s)", settings.APP_NAME, settings.APP_ENV)
    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        debug=settings.DEBUG,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    api = APIRouter(prefix=settings.API_V1_PREFIX)
    api.include_router(auth.router)
    api.include_router(users.router)
    api.include_router(drivers.router)
    api.include_router(uploads.router)
    api.include_router(orders.router)
    api.include_router(ws.router)
    app.include_router(api)

    return app


app = create_app()
