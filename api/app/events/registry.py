import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.events.envelope import EventEnvelope
from app.models import ProcessedEvent

logger = logging.getLogger(__name__)

HandlerFn = Callable[[AsyncSession, EventEnvelope], Awaitable[None]]


@dataclass(frozen=True)
class Handler:
    consumer: str
    fn: HandlerFn


_HANDLERS: dict[str, list[Handler]] = {}


def handles(event_type: str, consumer: str) -> Callable[[HandlerFn], HandlerFn]:
    """Register `fn` as a consumer of `event_type`. `consumer` must be stable across deploys."""

    def decorator(fn: HandlerFn) -> HandlerFn:
        _HANDLERS.setdefault(event_type, []).append(Handler(consumer, fn))
        return fn

    return decorator


def handlers_for(event_type: str) -> list[Handler]:
    return list(_HANDLERS.get(event_type, []))


async def dispatch(sessionmaker: async_sessionmaker[AsyncSession], envelope: EventEnvelope) -> int:
    """Run every handler for the event, each in its own transaction, at most once per consumer.

    Returns how many handlers actually ran (skipping ones already processed). Raises if a handler
    fails so the push request returns 5xx and Pub/Sub redelivers; handlers that already succeeded
    are skipped on redelivery.
    """
    handlers = handlers_for(envelope.type)
    if not handlers:
        logger.warning("No handlers registered for event type %s", envelope.type)
        return 0

    ran = 0
    for handler in handlers:
        async with sessionmaker() as session, session.begin():
            claimed = await session.execute(
                insert(ProcessedEvent)
                .values(
                    event_id=envelope.event_id,
                    consumer=handler.consumer,
                    event_type=envelope.type,
                )
                .on_conflict_do_nothing()
                .returning(ProcessedEvent.event_id)
            )
            if claimed.first() is None:
                logger.info("Skipping duplicate %s for %s", envelope.event_id, handler.consumer)
                continue
            await handler.fn(session, envelope)
            ran += 1
    return ran
