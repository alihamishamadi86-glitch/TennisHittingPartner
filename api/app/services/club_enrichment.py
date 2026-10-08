"""Find each club's website, phone, email and court-booking link, and save them.

Sources, cheapest and most trustworthy first:
  1. OpenStreetMap tags (website / phone / email / wikidata), re-read by element id;
  2. Wikidata's "official website" for clubs that link to it;
  3. an optional web search (Brave) for named clubs still without a website;
  4. the club's own website (homepage + contact page), crawled politely and safely.
Work happens in time-boxed batches so a worker request never exceeds Pub/Sub's deadline.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.integrations import web
from app.integrations.geo import GeoProviderError, OverpassSource
from app.integrations.websites import (
    WebsiteSearch,
    is_official_candidate,
    wikidata_official_website,
)
from app.models import City, Club, ClubKind
from app.services.contact_extraction import (
    contact_page_links,
    extract_contacts,
    parse_phone,
)

logger = logging.getLogger(__name__)

BATCH_FACILITIES = 6  # crawled: clubs & centres
BATCH_PUBLIC = 150  # tags only (crawled only if OSM lists a website)
BATCH_BUDGET_SECONDS = 45  # stays inside Pub/Sub's 60 s push deadline
CLUB_BUDGET_SECONDS = 20
GENERIC_NAMES = ("tennis courts", "tennis centre")


@dataclass(frozen=True)
class Found:
    website: str | None = None
    website_source: str | None = None
    phone: str | None = None
    email: str | None = None
    booking_url: str | None = None
    status: str = "no_website"


def _normalize_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().split(";")[0].strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value[:500]


def _is_named(club: Club) -> bool:
    return not club.name.lower().startswith(GENERIC_NAMES)


async def find_contacts(
    club: Club,
    tags: dict[str, str],
    city: City,
    search: WebsiteSearch | None,
) -> Found:
    website = _normalize_url(tags.get("website") or tags.get("contact:website") or tags.get("url"))
    source = "osm" if website else None
    if not website and club.website:
        website, source = club.website, club.website_source or "osm"
    if not website and (qid := tags.get("wikidata")):
        website = _normalize_url(await wikidata_official_website(qid))
        source = "wikidata" if website else None
    facility = club.kind is not ClubKind.PUBLIC_COURTS
    if not website and search is not None and facility and _is_named(club):
        found = await search.find(club.name, city.name, city.country_code)
        website = _normalize_url(found)
        source = "search" if website else None
    if website and not is_official_candidate(website):
        website, source = None, None  # a Facebook page or directory isn't the club's site

    phone = parse_phone(tags.get("phone") or tags.get("contact:phone") or "", city.country_code)
    email = (tags.get("email") or tags.get("contact:email") or "").strip() or None
    if not website:
        return Found(phone=phone, email=email, status="no_website" if not phone else "osm_only")

    try:
        pages = await web.fetch_pages([website])
        if pages:
            extra = contact_page_links(pages[0].html, pages[0].url)
            if extra:
                pages += await web.fetch_pages(extra)
    except web.FetchBlocked as exc:
        logger.info("Skipping %s: %s", website, exc)
        return Found(website, source, phone, email, status="blocked")
    except web.FetchError as exc:
        logger.info("Couldn't reach %s: %s", website, exc)
        return Found(website, source, phone, email, status="unreachable")

    contacts = extract_contacts([(p.url, p.html) for p in pages], city.country_code)
    return Found(
        website=pages[0].url if pages else website,
        website_source=source,
        phone=phone or contacts.phone,
        email=email or contacts.email,
        booking_url=contacts.booking_url,
        status="ok",
    )


def _needs_check(now: datetime) -> ColumnElement[bool]:
    stale = now - timedelta(days=get_settings().club_enrichment_refresh_days)
    return or_(Club.contacts_checked_at.is_(None), Club.contacts_checked_at < stale)


async def _pick_batch(session: AsyncSession, city_id: uuid.UUID, now: datetime) -> list[Club]:
    facilities = list(
        await session.scalars(
            select(Club)
            .where(
                Club.city_id == city_id,
                Club.active.is_(True),
                Club.kind != ClubKind.PUBLIC_COURTS,
                _needs_check(now),
            )
            .order_by(case((Club.kind == ClubKind.CLUB, 0), else_=1), Club.name)
            .limit(BATCH_FACILITIES)
        )
    )
    if facilities:
        return facilities
    return list(
        await session.scalars(
            select(Club)
            .where(
                Club.city_id == city_id,
                Club.active.is_(True),
                Club.kind == ClubKind.PUBLIC_COURTS,
                _needs_check(now),
            )
            .order_by(Club.name)
            .limit(BATCH_PUBLIC)
        )
    )


async def remaining(session: AsyncSession, city_id: uuid.UUID) -> int:
    rows = await session.scalars(
        select(Club.id).where(
            Club.city_id == city_id, Club.active.is_(True), _needs_check(datetime.now(UTC))
        )
    )
    return len(rows.all())


async def enrich_batch(
    session: AsyncSession,
    city_id: uuid.UUID,
    overpass: OverpassSource,
    search: WebsiteSearch | None,
) -> int:
    """Enrich the next batch of a city's clubs. Returns how many clubs were checked."""
    now = datetime.now(UTC)
    city = await session.get(City, city_id)
    if city is None:
        return 0
    clubs = await _pick_batch(session, city_id, now)
    if not clubs:
        return 0

    refs = [ref for club in clubs for ref in club.sources.get("osm", [])]
    try:
        tags_by_ref = await overpass.fetch_tags(refs)
    except GeoProviderError as exc:
        logger.warning("OSM tag lookup failed, continuing without: %s", exc)
        tags_by_ref = {}

    semaphore = asyncio.Semaphore(4)
    checked = 0

    async def one(club: Club) -> None:
        nonlocal checked
        # The venue's own OSM element first, then its courts: the club's tags win.
        own = club.external_key.removeprefix("osm:")
        refs = sorted(club.sources.get("osm", []), key=lambda ref: ref != own)
        tags: dict[str, str] = {}
        for ref in refs:
            for key, value in tags_by_ref.get(ref, {}).items():
                tags.setdefault(key, value)
        # Public courts are only crawled when a website is known (fresh tags or stored).
        crawl = club.kind is not ClubKind.PUBLIC_COURTS or "website" in tags or bool(club.website)
        async with semaphore:
            try:
                async with asyncio.timeout(CLUB_BUDGET_SECONDS):
                    found = (
                        await find_contacts(club, tags, city, search)
                        if crawl
                        else Found(
                            phone=parse_phone(tags.get("phone") or "", city.country_code),
                            email=tags.get("email"),
                            status="no_website",
                        )
                    )
            except TimeoutError:
                found = Found(website=club.website, status="timeout")
        club.website = found.website or club.website
        club.website_source = found.website_source or club.website_source
        club.phone = found.phone or parse_phone(club.phone or "", city.country_code)
        club.email = (found.email or club.email or "")[:254] or None
        # A successful crawl is authoritative for the booking link (it may have gone away);
        # otherwise keep what we had.
        club.booking_url = found.booking_url if found.status == "ok" else club.booking_url
        club.contacts_status = found.status
        club.contacts_checked_at = datetime.now(UTC)
        checked += 1

    tasks = [asyncio.create_task(one(club)) for club in clubs]
    try:
        async with asyncio.timeout(BATCH_BUDGET_SECONDS):
            await asyncio.gather(*tasks)
    except TimeoutError:
        for task in tasks:
            task.cancel()  # unchecked clubs are picked up by the next batch
    return checked
