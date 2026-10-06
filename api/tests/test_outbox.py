import json

import pytest
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.events.catalog import SYSTEM_PING
from app.events.outbox import record_event
from app.events.publisher import InMemoryPublisher
from app.events.relay import publish_committed, relay_outbox
from app.models import OutboxEvent


async def test_relay_publishes_pending_events_once() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        event = record_event(session, SYSTEM_PING, {"ping_id": "abc"})
        await session.commit()

    publisher = InMemoryPublisher()
    assert await relay_outbox(sessionmaker, publisher) == 1
    assert await relay_outbox(sessionmaker, publisher) == 0

    topic, data, attributes = publisher.messages[0]
    envelope = json.loads(data)
    assert topic == SYSTEM_PING
    assert attributes == {"event_type": SYSTEM_PING, "event_id": str(event.id)}
    assert envelope["event_id"] == str(event.id)
    assert envelope["type"] == SYSTEM_PING
    assert envelope["data"] == {"ping_id": "abc"}

    async with sessionmaker() as session:
        stored = await session.get(OutboxEvent, event.id)
        assert stored is not None
        assert stored.published_at is not None
        assert stored.attempts == 1


async def test_rolled_back_transaction_emits_no_event() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        record_event(session, SYSTEM_PING, {"ping_id": "abc"})
        await session.rollback()

    assert await relay_outbox(sessionmaker, InMemoryPublisher()) == 0


async def test_failed_publish_is_retried_later() -> None:
    class FailingPublisher:
        async def publish(self, topic: str, data: bytes, attributes: dict[str, str]) -> str:
            raise RuntimeError("pubsub down")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        record_event(session, SYSTEM_PING, {"ping_id": "abc"})
        await session.commit()

    assert await relay_outbox(sessionmaker, FailingPublisher()) == 0

    async with sessionmaker() as session:
        stored = (await session.scalars(select(OutboxEvent))).one()
        assert stored.published_at is None
        assert stored.attempts == 1
        assert stored.last_error is not None and "pubsub down" in stored.last_error

    assert await relay_outbox(sessionmaker, InMemoryPublisher()) == 1


async def test_unknown_event_type_is_rejected() -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(ValueError, match="Unknown event type"):
            record_event(session, "made.up", {})


async def test_publish_committed_targets_only_given_events() -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        mine = record_event(session, SYSTEM_PING, {"ping_id": "mine"})
        record_event(session, SYSTEM_PING, {"ping_id": "other"})
        await session.commit()

    publisher = InMemoryPublisher()
    await publish_committed(sessionmaker, publisher, [mine.id])

    assert [attrs["event_id"] for _, _, attrs in publisher.messages] == [str(mine.id)]


async def test_publish_committed_never_raises() -> None:
    class FailingPublisher:
        async def publish(self, topic: str, data: bytes, attributes: dict[str, str]) -> str:
            raise RuntimeError("pubsub down")

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        event = record_event(session, SYSTEM_PING, {"ping_id": "abc"})
        await session.commit()

    await publish_committed(sessionmaker, FailingPublisher(), [event.id])
