"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload   (from the backend/ folder)
API docs:     http://localhost:8000/docs
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, log_requests
from app.core.security import TokenVerifier, build_jwks_resolver
from app.database.connection import create_pool
from app.modules.activities.router import router as activities_router
from app.modules.assets.router import router as assets_router
from app.modules.ai.client import GeminiClient
from app.modules.ai.deps import AiRateLimiter
from app.modules.health.router import router as health_router
from app.modules.images.client import PixabayClient
from app.modules.images.router import router as images_router
from app.modules.lessons.router import router as lessons_router
from app.modules.saved_pages.router import router as saved_pages_router
from app.modules.saved_slides.router import router as saved_slides_router
from app.modules.slides.ai import router as slides_ai_router
from app.modules.slides.narration import router as narration_router
from app.modules.listening.client import OpenAiTranscriber
from app.modules.listening.ask import router as ask_router
from app.modules.listening.router import router as listening_router
from app.modules.slides.router import router as slides_router
from app.modules.speech.client import GeminiSpeechClient
from app.modules.speech.router import router as speech_router
from app.modules.stickers.router import router as stickers_router
from app.modules.suggestions.router import router as suggestions_router
from app.modules.teachers.router import router as teachers_router
from app.shared.errors.handlers import register_error_handlers


def create_app(settings: Settings | None = None, *, connect_db: bool = True) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db_pool = await create_pool(settings) if connect_db else None
        ai_http = None
        if settings.gemini_api_key is not None and getattr(app.state, "ai_client", None) is None:
            ai_http = httpx.AsyncClient(timeout=settings.gemini_timeout_seconds)
            app.state.ai_client = GeminiClient(
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_model,
                ai_http,
                fallback_model=settings.gemini_fallback_model or None,
            )
        if ai_http is not None and getattr(app.state, "speech_client", None) is None:
            app.state.speech_client = GeminiSpeechClient(
                settings.gemini_api_key.get_secret_value(),
                settings.gemini_tts_model,
                ai_http,
                fallback_model=settings.gemini_tts_fallback_model or None,
            )
        image_http = None
        if settings.pixabay_api_key is not None and getattr(app.state, "image_search", None) is None:
            image_http = httpx.AsyncClient(timeout=30)
            app.state.image_search = PixabayClient(settings.pixabay_api_key.get_secret_value(), image_http)
        listen_http = None
        if settings.openai_api_key is not None and getattr(app.state, "transcriber", None) is None:
            listen_http = httpx.AsyncClient(timeout=settings.openai_timeout_seconds)
            app.state.transcriber = OpenAiTranscriber(
                settings.openai_api_key.get_secret_value(), settings.openai_transcribe_model, listen_http
            )
        try:
            yield
        finally:
            if listen_http is not None:
                await listen_http.aclose()
            if image_http is not None:
                await image_http.aclose()
            if ai_http is not None:
                await ai_http.aclose()
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
    app.state.ai_client = None  # set at startup when GEMINI_API_KEY is configured; tests may inject a fake
    app.state.ai_limiter = AiRateLimiter(settings.ai_requests_per_hour)
    app.state.speech_client = None  # set at startup with GEMINI_API_KEY; tests may inject a fake
    app.state.speech_limiter = AiRateLimiter(settings.speech_requests_per_hour)
    app.state.transcriber = None  # set at startup with OPENAI_API_KEY; tests may inject a fake
    app.state.listen_limiter = AiRateLimiter(settings.listen_requests_per_hour)
    app.state.ask_limiter = AiRateLimiter(settings.ask_requests_per_hour)
    app.state.image_search = None  # set at startup with PIXABAY_API_KEY; tests may inject a fake
    app.state.image_limiter = AiRateLimiter(settings.image_requests_per_hour)
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
    app.include_router(lessons_router)
    app.include_router(activities_router)
    app.include_router(suggestions_router)
    app.include_router(speech_router)
    app.include_router(assets_router)
    app.include_router(saved_pages_router)
    app.include_router(saved_slides_router)
    app.include_router(slides_ai_router)
    app.include_router(narration_router)
    app.include_router(listening_router)
    app.include_router(ask_router)
    app.include_router(slides_router)
    app.include_router(stickers_router)
    app.include_router(images_router)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn app.main:app` builds the app on first access, so importing
    # this module (e.g. in tests) does not require a .env file.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
