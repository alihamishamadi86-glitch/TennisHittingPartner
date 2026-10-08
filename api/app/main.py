"""API service entrypoint (public REST API consumed by the Next.js app)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.csrf import origin_check_middleware
from app.core.logging import configure_logging
from app.core.middleware import trace_context_middleware
from app.routers import (
    admin,
    auth,
    availability,
    bookings,
    clubs,
    dev_storage,
    geo,
    health,
    levels,
    me,
    profiles,
    system,
)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.gcp_project_id)

    app = FastAPI(title="Tennis Hitting Partner API", version="0.1.0")
    app.middleware("http")(origin_check_middleware)
    app.middleware("http")(trace_context_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(profiles.router)
    app.include_router(levels.router)
    app.include_router(admin.router)
    app.include_router(clubs.router)
    app.include_router(availability.router)
    app.include_router(bookings.router)
    app.include_router(geo.router)
    if settings.storage_backend == "local":
        app.include_router(dev_storage.router)
    if settings.enable_system_ping:
        app.include_router(system.router)
    return app


app = create_app()
