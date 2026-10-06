import asyncio
import logging
import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.catalog import topic_name
from app.events.envelope import EventEnvelope
from app.events.publisher import Publisher
from app.models import OutboxEvent

logger = logging.getLogger(__name__)

IMMEDIATE_PUBLISH_TIMEOUT_SECONDS = 2.0


async def relay_outbox(
    sessionmaker: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    batch_size: int = 100,
    event_ids: Sequence[uuid.UUID] | None = None,
) -> int:
    """Publish pending outbox events (optionally only `event_ids`). Returns the number published.

    `FOR UPDATE SKIP LOCKED` lets several relays (API background task, scheduler sweep) run
    concurrently without publishing the same row twice in the common case. Consumers are still
    idempotent, because a crash between publish and commit re-publishes on the next run.
    """
    published = 0
    query = select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
    if event_ids is not None:
        query = query.where(OutboxEvent.id.in_(event_ids))
    async with sessionmaker() as session, session.begin():
        rows = (
            await session.scalars(
                query.order_by(OutboxEvent.occurred_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for event in rows:
            envelope = EventEnvelope(
                event_id=event.id,
                type=event.event_type,
                version=event.version,
                occurred_at=event.occurred_at,
                data=event.payload,
            )
            event.attempts += 1
            try:
                await publisher.publish(
                    topic_name(event.event_type),
                    envelope.model_dump_json().encode(),
                    {"event_type": event.event_type, "event_id": str(event.id)},
                )
            except Exception as exc:
                event.last_error = repr(exc)[:2000]
                logger.exception("Failed to publish outbox event %s", event.id)
                continue
            event.published_at = func.now()
            event.last_error = None
            published += 1

    if published:
        logger.info("Relayed %d outbox events", published)
    return published


async def publish_committed(
    sessionmaker: async_sessionmaker[AsyncSession],
    publisher: Publisher,
    event_ids: Sequence[uuid.UUID],
) -> None:
    """Best-effort immediate publish of events a request just committed.

    Runs inline (not as a background task) because Cloud Run throttles CPU once the response is
    sent. Never raises: anything not published here is picked up by the scheduled sweep.
    """
    try:
        async with asyncio.timeout(IMMEDIATE_PUBLISH_TIMEOUT_SECONDS):
            await relay_outbox(sessionmaker, publisher, len(event_ids), event_ids)
    except Exception:
        logger.warning("Immediate publish failed; deferring to outbox sweep", exc_info=True)
