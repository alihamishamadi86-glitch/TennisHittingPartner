import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.events.catalog import CLUBS_DISCOVERY_REQUESTED
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.integrations.geo import BBox, GeoProviderError, get_place_sources
from app.models import City, DiscoveryStatus
from app.services.clubs import fetch_places, save_sites, set_discovery_state

logger = logging.getLogger(__name__)


async def _set_state(city_id: uuid.UUID, status: DiscoveryStatus, error: str | None = None) -> int:
    """Persist discovery state immediately (own transaction) so pollers see progress even if
    the handler's transaction later rolls back for a retry. Returns attempts so far."""
    async with get_sessionmaker()() as session, session.begin():
        city = await set_discovery_state(session, city_id, status, error)
        return city.attempts if city else 0


@handles(CLUBS_DISCOVERY_REQUESTED, consumer="clubs.discover")
async def discover_clubs(session: AsyncSession, envelope: EventEnvelope) -> None:
    city_id = uuid.UUID(envelope.data["city_id"])
    city = await session.get(City, city_id)
    if city is None or city.status is DiscoveryStatus.READY:
        return  # deleted, or already discovered by an earlier delivery

    attempts = await _set_state(city_id, DiscoveryStatus.RUNNING)
    bbox = BBox(city.bbox_south, city.bbox_west, city.bbox_north, city.bbox_east)
    try:
        sites, warnings = await fetch_places(get_place_sources(), bbox)
    except GeoProviderError as exc:
        final = attempts >= get_settings().discovery_max_attempts
        await _set_state(
            city_id, DiscoveryStatus.FAILED if final else DiscoveryStatus.PENDING, str(exc)
        )
        if final:
            logger.error("Club discovery for %s failed permanently: %s", city.key, exc)
            return
        raise  # Pub/Sub redelivers with backoff

    await session.refresh(city)
    await save_sites(session, city, sites)
    if warnings:
        city.last_error = "Partial results: " + "; ".join(warnings)
    logger.info("Discovered %d tennis sites for %s", len(sites), city.key)
