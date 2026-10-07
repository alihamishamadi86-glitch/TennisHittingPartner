"""Worker service entrypoint: receives Pub/Sub push deliveries and scheduled task calls.

Not publicly reachable in GCP — only Pub/Sub, Cloud Scheduler and Cloud Tasks (via their
OIDC-authenticated service account) may invoke it.
"""

import asyncio
import base64
import binascii
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import configure_logging
from app.core.middleware import trace_context_middleware
from app.core.push_auth import verify_push_request
from app.events import handlers  # noqa: F401  (import registers event handlers)
from app.events.envelope import EventEnvelope
from app.events.outbox import commit_and_publish
from app.events.publisher import get_publisher
from app.events.registry import dispatch
from app.events.relay import relay_outbox
from app.routers import health
from app.services.clubs import queue_refresh, stale_cities

logger = logging.getLogger(__name__)


class PushMessage(BaseModel):
    data: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)
    message_id: str = Field(default="", alias="messageId")


class PushRequest(BaseModel):
    message: PushMessage
    subscription: str = ""


async def _relay_loop(interval: float) -> None:
    settings = get_settings()
    while True:
        try:
            await relay_outbox(
                get_sessionmaker(), get_publisher(), settings.outbox_relay_batch_size
            )
        except Exception:
            logger.exception("Outbox relay loop iteration failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    interval = get_settings().outbox_relay_interval_seconds
    task = asyncio.create_task(_relay_loop(interval)) if interval > 0 else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_worker_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.gcp_project_id)

    app = FastAPI(title="Tennis Hitting Partner Worker", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(trace_context_middleware)
    app.include_router(health.router)

    @app.post(
        "/pubsub/push",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(verify_push_request)],
    )
    async def pubsub_push(body: PushRequest) -> Response:
        try:
            envelope = EventEnvelope.model_validate_json(base64.b64decode(body.message.data))
        except (binascii.Error, ValidationError) as exc:
            # Non-2xx → Pub/Sub retries, then routes to the dead-letter topic for inspection.
            logger.error("Malformed message %s: %s", body.message.message_id, exc)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Malformed message") from exc

        ran = await dispatch(get_sessionmaker(), envelope)
        logger.info(
            "Handled %s",
            envelope.type,
            extra={"extra_fields": {"event_id": str(envelope.event_id), "handlers_ran": ran}},
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/tasks/outbox-relay", dependencies=[Depends(verify_push_request)])
    async def outbox_relay() -> dict[str, int]:
        published = await relay_outbox(
            get_sessionmaker(), get_publisher(), settings.outbox_relay_batch_size
        )
        return {"published": published}

    @app.post("/tasks/refresh-cities", dependencies=[Depends(verify_push_request)])
    async def refresh_cities() -> dict[str, int]:
        """Daily (Cloud Scheduler): re-discover clubs for cities whose data is stale."""
        async with get_sessionmaker()() as session:
            cities = await stale_cities(session)
            for city in cities:
                queue_refresh(session, city)
            await commit_and_publish(session)
        return {"queued": len(cities)}

    return app


app = create_worker_app()
