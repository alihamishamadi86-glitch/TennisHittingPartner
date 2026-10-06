from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import EVENT_TYPES
from app.models import OutboxEvent


def record_event(
    session: AsyncSession, event_type: str, data: dict[str, Any], version: int = 1
) -> OutboxEvent:
    """Stage an event in the outbox. It is persisted only if the caller's transaction commits."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    event = OutboxEvent(event_type=event_type, version=version, payload=data)
    session.add(event)
    return event
