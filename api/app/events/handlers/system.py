import uuid

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import SYSTEM_PING
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.models import SystemPing


@handles(SYSTEM_PING, consumer="system.ping.mark_received")
async def mark_ping_received(session: AsyncSession, envelope: EventEnvelope) -> None:
    await session.execute(
        update(SystemPing)
        .where(SystemPing.id == uuid.UUID(envelope.data["ping_id"]))
        .values(received_at=func.now())
    )
