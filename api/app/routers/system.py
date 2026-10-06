import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, get_sessionmaker
from app.events.catalog import SYSTEM_PING
from app.events.outbox import record_event
from app.events.publisher import get_publisher
from app.events.relay import publish_committed
from app.models import SystemPing
from app.schemas.system import SystemPingOut

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/ping", status_code=status.HTTP_202_ACCEPTED)
async def create_ping(session: Annotated[AsyncSession, Depends(get_session)]) -> SystemPingOut:
    """Emit a `system.ping` event; poll GET /system/ping/{id} until `received_at` is set."""
    ping = SystemPing(id=uuid.uuid4())
    session.add(ping)
    event = record_event(session, SYSTEM_PING, {"ping_id": str(ping.id)})
    await session.commit()
    await session.refresh(ping)
    await publish_committed(get_sessionmaker(), get_publisher(), [event.id])
    return SystemPingOut.model_validate(ping)


@router.get("/ping/{ping_id}")
async def get_ping(
    ping_id: uuid.UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> SystemPingOut:
    ping = await session.get(SystemPing, ping_id)
    if ping is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ping not found")
    return SystemPingOut.model_validate(ping)
