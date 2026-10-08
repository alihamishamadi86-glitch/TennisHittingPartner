"""City club discovery and club queries."""

import asyncio
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from geoalchemy2.types import Geography
from sqlalchemy import ColumnElement, Float, and_, cast, delete, func, null, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import CLUBS_DISCOVERY_REQUESTED
from app.events.outbox import record_event
from app.integrations.geo import BBox, GeocodedCity, Geocoder, GeoProviderError, PlaceSource
from app.models import (
    City,
    CityAlias,
    Club,
    DiscoveryStatus,
    PartnerProfile,
    PartnerStatus,
    PostalCode,
    User,
    UserClub,
    UserRole,
)
from app.services.club_merge import Site, build_sites
from app.services.contact_extraction import parse_phone

logger = logging.getLogger(__name__)

# A discovery stuck in pending/running longer than this is re-queued on the next request.
STUCK_AFTER = timedelta(minutes=15)
MAX_MY_CLUBS = 20
GEOCODER_RETRY_DELAY_S = 1.0


class CityNotFoundError(Exception):
    pass


class UnknownClubError(Exception):
    pass


class PostcodeNotFoundError(Exception):
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
    pause_before_geocode: bool = False,
) -> City:
    """Resolve the city (cached) and queue club discovery if it's new or stale.

    `pause_before_geocode`: the caller just made a geocoder request (e.g. for a postcode), so
    wait before another one — Nominatim allows 1 request/second.
    """
    alias_key = city_key(city, region, country_code)
    alias = await session.get(CityAlias, alias_key)
    existing = await session.get(City, alias.city_id) if alias else None

    if existing is None:
        if pause_before_geocode:
            await asyncio.sleep(GEOCODER_RETRY_DELAY_S)
        geocoded = await geocoder.geocode_city(city, region, country_code)
        if geocoded is None and region:
            # The region is free text and often wrong for the geocoder (a postcode, an
            # abbreviation it doesn't know); fall back to city + country.
            await asyncio.sleep(GEOCODER_RETRY_DELAY_S)  # Nominatim allows 1 request/second
            geocoded = await geocoder.geocode_city(city, None, country_code)
        if geocoded is None:
            raise CityNotFoundError
        existing, created = await _get_or_create_city(session, geocoded)
        await session.execute(
            pg_insert(CityAlias).values(key=alias_key, city_id=existing.id).on_conflict_do_nothing()
        )
        if created:
            record_event(session, CLUBS_DISCOVERY_REQUESTED, {"city_id": str(existing.id)})
            await session.flush()
            return existing

    if force or _needs_discovery(existing):
        _queue(session, existing)
    await session.flush()
    return existing


async def _get_or_create_city(session: AsyncSession, geocoded: GeocodedCity) -> tuple[City, bool]:
    """Idempotent under concurrency: two requests for a new city both succeed, and only the
    one that inserted reports `created` (so discovery is queued once)."""
    key = city_key(geocoded.name, geocoded.region, geocoded.country_code)
    inserted_id = await session.scalar(
        pg_insert(City)
        .values(
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
            club_count=0,
        )
        .on_conflict_do_nothing(index_elements=[City.key])
        .returning(City.id)
    )
    city = await session.scalar(
        select(City).where(City.key == key).execution_options(populate_existing=True)
    )
    assert city is not None
    return city, inserted_id is not None


def normalize_postcode(postal_code: str) -> str:
    return re.sub(r"\s+", " ", postal_code.strip().upper())


async def resolve_postcode(
    session: AsyncSession, geocoder: Geocoder, postal_code: str, country_code: str
) -> tuple[PostalCode, bool]:
    """Geocode a postal code (cached). Returns (postcode, freshly_geocoded)."""
    code = normalize_postcode(postal_code)
    cached = await session.get(PostalCode, (country_code, code))
    if cached is not None:
        return cached, False
    geocoded = await geocoder.geocode_postcode(code, country_code)
    if geocoded is None:
        raise PostcodeNotFoundError
    # Concurrent lookups of the same new postcode (two tabs, React's double effects) race
    # here; whoever inserts second just reads the row back.
    await session.execute(
        pg_insert(PostalCode)
        .values(
            country_code=country_code,
            postal_code=code,
            lat=geocoded.lat,
            lon=geocoded.lon,
            city_name=geocoded.city,
            region=geocoded.region,
        )
        .on_conflict_do_nothing()
    )
    postcode = await session.get(PostalCode, (country_code, code), populate_existing=True)
    assert postcode is not None
    return postcode, True


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
            "phone": parse_phone(site.phone or "", city.country_code),
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


async def my_club_ids(session: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(UserClub.club_id)
            .join(Club, Club.id == UserClub.club_id)
            .where(UserClub.user_id == user_id)
            .order_by(Club.name, Club.id)
        )
    )


async def set_my_clubs(
    session: AsyncSession, user: User, club_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """Replace the user's courts. Courts that dropped out of discovery stay if already saved."""
    unique = list(dict.fromkeys(club_ids))
    if len(unique) > MAX_MY_CLUBS:
        raise UnknownClubError(f"Choose at most {MAX_MY_CLUBS} courts")
    kept = set(await my_club_ids(session, user.id))
    new = [club_id for club_id in unique if club_id not in kept]
    if new:
        found = set(
            await session.scalars(select(Club.id).where(Club.id.in_(new), Club.active.is_(True)))
        )
        if found != set(new):
            raise UnknownClubError("Unknown club")
    await session.execute(
        delete(UserClub).where(UserClub.user_id == user.id, UserClub.club_id.not_in(unique))
    )
    for club_id in new:
        session.add(UserClub(user_id=user.id, club_id=club_id))
    await session.flush()
    return unique


@dataclass
class CourtCounts:
    partners: int = 0
    players: int = 0


async def court_counts(
    session: AsyncSession, club_ids: list[uuid.UUID], exclude_user_id: uuid.UUID
) -> dict[uuid.UUID, CourtCounts]:
    """Approved partners and players who list each court (not counting the asking user)."""
    counts = {club_id: CourtCounts() for club_id in club_ids}
    if not club_ids:
        return counts
    approved_partner = and_(
        User.role == UserRole.PARTNER, PartnerProfile.status == PartnerStatus.APPROVED
    )
    rows = await session.execute(
        select(
            UserClub.club_id,
            func.count().filter(approved_partner),
            func.count().filter(User.role == UserRole.CLIENT),
        )
        .join(User, User.id == UserClub.user_id)
        .outerjoin(PartnerProfile, PartnerProfile.user_id == UserClub.user_id)
        .where(
            UserClub.club_id.in_(club_ids),
            UserClub.user_id != exclude_user_id,
            User.is_active.is_(True),
        )
        .group_by(UserClub.club_id)
    )
    for club_id, partners, players in rows.all():
        counts[club_id] = CourtCounts(partners=partners, players=players)
    return counts
