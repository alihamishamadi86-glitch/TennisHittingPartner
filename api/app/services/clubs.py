"""City club discovery and club queries."""

import asyncio
import logging
import re
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta

from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from geoalchemy2.types import Geography
from sqlalchemy import ColumnElement, Float, cast, delete, null, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import CLUBS_DISCOVERY_REQUESTED
from app.events.outbox import record_event
from app.integrations.geo import BBox, GeocodedCity, Geocoder, GeoProviderError, PlaceSource
from app.models import City, CityAlias, Club, DiscoveryStatus, PartnerClub, User
from app.services.club_merge import Site, build_sites

logger = logging.getLogger(__name__)

# A discovery stuck in pending/running longer than this is re-queued on the next request.
STUCK_AFTER = timedelta(minutes=15)
MAX_PARTNER_CLUBS = 20


class CityNotFoundError(Exception):
    pass


class UnknownClubError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def city_key(name: str, region: str | None, country_code: str) -> str:
    def norm(value: str | None) -> str:
        text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    return f"{norm(name)}|{norm(region)}|{country_code.lower()}"


def _point(lat: float, lon: float) -> ColumnElement[Geography]:
    return cast(ST_SetSRID(ST_MakePoint(lon, lat), 4326), Geography)


def _needs_discovery(city: City) -> bool:
    now = _now()
    if city.status is DiscoveryStatus.FAILED:
        return True
    if city.status is DiscoveryStatus.READY:
        refresh = timedelta(days=get_settings().city_refresh_days)
        return city.discovered_at is None or city.discovered_at < now - refresh
    return city.updated_at < now - STUCK_AFTER  # pending/running but apparently stuck


def _queue(session: AsyncSession, city: City) -> None:
    city.status = DiscoveryStatus.PENDING
    city.attempts = 0
    city.updated_at = _now()
    record_event(session, CLUBS_DISCOVERY_REQUESTED, {"city_id": str(city.id)})


async def request_discovery(
    session: AsyncSession,
    geocoder: Geocoder,
    *,
    city: str,
    region: str | None,
    country_code: str,
    force: bool = False,
) -> City:
    """Resolve the city (cached) and queue club discovery if it's new or stale."""
    alias_key = city_key(city, region, country_code)
    alias = await session.get(CityAlias, alias_key)
    existing = await session.get(City, alias.city_id) if alias else None

    if existing is None:
        geocoded = await geocoder.geocode_city(city, region, country_code)
        if geocoded is None:
            raise CityNotFoundError
        existing, created = await _get_or_create_city(session, geocoded)
        await session.merge(CityAlias(key=alias_key, city_id=existing.id))
        if created:
            record_event(session, CLUBS_DISCOVERY_REQUESTED, {"city_id": str(existing.id)})
            await session.flush()
            return existing

    if force or _needs_discovery(existing):
        _queue(session, existing)
    await session.flush()
    return existing


async def _get_or_create_city(session: AsyncSession, geocoded: GeocodedCity) -> tuple[City, bool]:
    key = city_key(geocoded.name, geocoded.region, geocoded.country_code)
    city = await session.scalar(select(City).where(City.key == key))
    if city is not None:
        return city, False
    city = City(
        id=uuid.uuid4(),
        name=geocoded.name,
        region=geocoded.region,
        country_code=geocoded.country_code,
        key=key,
        lat=geocoded.lat,
        lon=geocoded.lon,
        bbox_south=geocoded.bbox.south,
        bbox_west=geocoded.bbox.west,
        bbox_north=geocoded.bbox.north,
        bbox_east=geocoded.bbox.east,
        geocoder=geocoded.provider,
        geocoder_place_id=geocoded.place_id,
        status=DiscoveryStatus.PENDING,
        attempts=0,
    )
    session.add(city)
    await session.flush()
    return city, True


# --- Worker side ------------------------------------------------------------------------


async def fetch_places(
    sources: tuple[PlaceSource, ...], bbox: BBox
) -> tuple[list[Site], list[str]]:
    """Query all sources concurrently. Succeeds if at least one source answers."""
    results = await asyncio.gather(*(s.fetch(bbox) for s in sources), return_exceptions=True)
    places, errors = [], []
    for source, result in zip(sources, results, strict=True):
        if isinstance(result, BaseException):
            logger.warning("Place source %s failed: %r", source.name, result)
            errors.append(f"{source.name}: {result}")
        else:
            places.extend(result)
    if len(errors) == len(sources):
        raise GeoProviderError("; ".join(errors))
    return build_sites(places), errors


async def save_sites(session: AsyncSession, city: City, sites: list[Site]) -> None:
    now = _now()
    existing = {
        club.external_key: club
        for club in await session.scalars(select(Club).where(Club.city_id == city.id))
    }
    seen: set[str] = set()
    for site in sites:
        if site.external_key in seen:
            continue
        seen.add(site.external_key)
        fields = {
            "name": site.name[:200],
            "kind": site.kind,
            "lat": site.lat,
            "lon": site.lon,
            "location": f"SRID=4326;POINT({site.lon} {site.lat})",
            "address": site.address,
            "website": (site.website or "")[:500] or None,
            "phone": (site.phone or "")[:64] or None,
            "court_count": site.court_count,
            "surface": site.surface,
            "access": site.access,
            "lit": site.lit,
            "sources": site.sources,
            "active": True,
            "last_seen_at": now,
        }
        club = existing.get(site.external_key)
        if club is None:
            session.add(Club(city_id=city.id, external_key=site.external_key, **fields))
        else:
            for key, value in fields.items():
                setattr(club, key, value)
    # Keep clubs that disappeared (partners may be linked to them) but hide them.
    await session.execute(
        update(Club)
        .where(Club.city_id == city.id, Club.external_key.not_in(seen or {""}))
        .values(active=False)
    )
    city.status = DiscoveryStatus.READY
    city.discovered_at = now
    city.club_count = len(seen)
    city.attempts = 0
    city.last_error = None


async def set_discovery_state(
    session: AsyncSession, city_id: uuid.UUID, status: DiscoveryStatus, error: str | None = None
) -> City | None:
    city = await session.get(City, city_id, with_for_update=True)
    if city is None:
        return None
    city.status = status
    if status is DiscoveryStatus.RUNNING:
        city.attempts += 1
    if error is not None:
        city.last_error = error[:2000]
    return city


async def stale_cities(session: AsyncSession, limit: int = 20) -> list[City]:
    cutoff = _now() - timedelta(days=get_settings().city_refresh_days)
    return list(
        await session.scalars(
            select(City)
            .where(City.status == DiscoveryStatus.READY, City.discovered_at < cutoff)
            .order_by(City.discovered_at)
            .limit(limit)
        )
    )


def queue_refresh(session: AsyncSession, city: City) -> None:
    _queue(session, city)


# --- Queries ----------------------------------------------------------------------------


async def list_clubs(
    session: AsyncSession,
    *,
    city_id: uuid.UUID | None = None,
    near: tuple[float, float] | None = None,
    radius_km: float = 25,
    query: str | None = None,
    limit: int = 200,
) -> list[tuple[Club, float | None]]:
    distance = (ST_Distance(Club.location, _point(*near)) if near else null().cast(Float)).label(
        "distance_m"
    )
    stmt = select(Club, distance).where(Club.active.is_(True))
    if city_id:
        stmt = stmt.where(Club.city_id == city_id)
    if near:
        stmt = stmt.where(ST_DWithin(Club.location, _point(*near), radius_km * 1000))
    if query:
        stmt = stmt.where(Club.name.ilike(f"%{query.strip()}%"))
    stmt = stmt.order_by(distance if near else Club.name).limit(limit)
    return [(club, dist) for club, dist in (await session.execute(stmt)).all()]


async def partner_club_ids(session: AsyncSession, partner_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(PartnerClub.club_id).where(PartnerClub.partner_id == partner_id)
        )
    )


async def set_partner_clubs(
    session: AsyncSession, partner: User, club_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(club_ids))
    if len(unique) > MAX_PARTNER_CLUBS:
        raise UnknownClubError(f"Choose at most {MAX_PARTNER_CLUBS} clubs")
    if unique:
        found = set(
            await session.scalars(select(Club.id).where(Club.id.in_(unique), Club.active.is_(True)))
        )
        if found != set(unique):
            raise UnknownClubError("Unknown club")
    await session.execute(delete(PartnerClub).where(PartnerClub.partner_id == partner.id))
    for club_id in unique:
        session.add(PartnerClub(partner_id=partner.id, club_id=club_id))
    await session.flush()
    return unique
