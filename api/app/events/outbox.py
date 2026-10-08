from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.events.catalog import EVENT_TYPES
from app.events.publisher import get_publisher
from app.events.relay import publish_committed
from app.models import OutboxEvent

_SESSION_KEY = "outbox_events"


def record_event(
    session: AsyncSession, event_type: str, data: dict[str, Any], version: int = 1
) -> OutboxEvent:
    """Stage an event in the outbox. It is persisted only if the caller's transaction commits."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    event = OutboxEvent(event_type=event_type, version=version, payload=data)
    session.add(event)
    session.info.setdefault(_SESSION_KEY, []).append(event)
    return event


async def commit_and_publish(session: AsyncSession) -> None:
    """Commit, then immediately publish the events this session recorded (best effort;
    the scheduled outbox sweep delivers anything that fails here)."""
    events = take_recorded(session)
    await session.commit()
    await publish_events(events)


def take_recorded(session: AsyncSession) -> list[OutboxEvent]:
    """Events recorded in this session so far (and forget them)."""
    events: list[OutboxEvent] = session.info.pop(_SESSION_KEY, [])
    return events


async def publish_events(events: list[OutboxEvent]) -> None:
    """Publish already-committed events now rather than waiting for the sweep."""
    if events:
        await publish_committed(get_sessionmaker(), get_publisher(), [e.id for e in events])
