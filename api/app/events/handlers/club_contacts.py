import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.catalog import CLUBS_ENRICHMENT_REQUESTED
from app.events.envelope import EventEnvelope
from app.events.outbox import record_event
from app.events.registry import handles
from app.integrations.geo import get_overpass
from app.integrations.websites import get_website_search
from app.services.club_enrichment import enrich_batch, remaining


@handles(CLUBS_ENRICHMENT_REQUESTED, consumer="clubs.enrich_contacts")
async def enrich_contacts(session: AsyncSession, envelope: EventEnvelope) -> None:
    """One time-boxed batch, then hand the rest of the city to the next delivery."""
    city_id = uuid.UUID(envelope.data["city_id"])
    checked = await enrich_batch(session, city_id, get_overpass(), get_website_search())
    if checked and await remaining(session, city_id):
        record_event(session, CLUBS_ENRICHMENT_REQUESTED, {"city_id": str(city_id)})
