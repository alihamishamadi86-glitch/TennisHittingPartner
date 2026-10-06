"""API service entrypoint (public REST API consumed by the Next.js app)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import trace_context_middleware
from app.routers import health, system


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.gcp_project_id)

    app = FastAPI(title="Tennis Hitting Partner API", version="0.1.0")
    app.middleware("http")(trace_context_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    if settings.enable_system_ping:
        app.include_router(system.router)
    return app


app = create_app()
