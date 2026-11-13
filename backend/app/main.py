"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload   (from the backend/ folder)
API docs:     http://localhost:8000/docs
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_requests
from app.core.security import TokenVerifier, build_jwks_resolver
from app.database.connection import create_pool
from app.modules.health.router import router as health_router
from app.modules.teachers.router import router as teachers_router
from app.shared.errors.handlers import register_error_handlers


def create_app(settings: Settings | None = None, *, connect_db: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db_pool = await create_pool(settings) if connect_db else None
        try:
            yield
        finally:
            if app.state.db_pool is not None:
                await app.state.db_pool.close()

    app = FastAPI(
        title="Smart Classroom Assistant API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.token_verifier = TokenVerifier(
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        key_resolver=build_jwks_resolver(settings.jwks_url),
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.middleware("http")(log_requests)
    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(teachers_router)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn app.main:app` builds the app on first access, so importing
    # this module (e.g. in tests) does not require a .env file.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
