import base64
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.events.catalog import SYSTEM_PING
from app.events.envelope import EventEnvelope
from app.events.publisher import InMemoryPublisher
from app.models import ProcessedEvent, SystemPing


def push_body(data: bytes) -> dict[str, object]:
    return {
        "message": {"data": base64.b64encode(data).decode(), "messageId": "1", "attributes": {}},
        "subscription": "projects/thp-local/subscriptions/system.ping.worker",
    }


async def create_ping() -> uuid.UUID:
    async with get_sessionmaker()() as session:
        ping = SystemPing(id=uuid.uuid4())
        session.add(ping)
        await session.commit()
        return ping.id


async def test_push_dispatches_handler_exactly_once(worker_client: AsyncClient) -> None:
    ping_id = await create_ping()
    envelope = EventEnvelope(
        event_id=uuid.uuid4(),
        type=SYSTEM_PING,
        occurred_at=datetime.now(UTC),
        data={"ping_id": str(ping_id)},
    )
    body = push_body(envelope.model_dump_json().encode())

    first = await worker_client.post("/pubsub/push", json=body)
    redelivery = await worker_client.post("/pubsub/push", json=body)

    assert first.status_code == 204
    assert redelivery.status_code == 204
    async with get_sessionmaker()() as session:
        ping = await session.get(SystemPing, ping_id)
        assert ping is not None and ping.received_at is not None
        processed = await session.scalar(select(func.count()).select_from(ProcessedEvent))
        assert processed == 1


async def test_malformed_message_is_rejected(worker_client: AsyncClient) -> None:
    response = await worker_client.post("/pubsub/push", json=push_body(b"not json"))
    assert response.status_code == 400


async def test_push_requires_token_when_auth_enabled(worker_client: AsyncClient) -> None:
    from app.worker import app

    app.dependency_overrides[get_settings] = lambda: Settings(
        push_auth_enabled=True, push_auth_audience="https://worker"
    )
    try:
        response = await worker_client.post("/pubsub/push", json=push_body(b"{}"))
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


async def test_ping_round_trip(
    api_client: AsyncClient, worker_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    """M0 exit criterion, in-process: API → outbox → publisher → worker push → handler."""
    created = await api_client.post("/system/ping")
    assert created.status_code == 202
    ping_id = created.json()["id"]
    assert created.json()["received_at"] is None

    assert len(publisher.messages) == 1
    _, data, _ = publisher.messages[0]
    pushed = await worker_client.post("/pubsub/push", json=push_body(data))
    assert pushed.status_code == 204

    fetched = await api_client.get(f"/system/ping/{ping_id}")
    assert fetched.json()["received_at"] is not None
