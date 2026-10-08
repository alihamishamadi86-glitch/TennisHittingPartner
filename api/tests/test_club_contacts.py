from collections.abc import Callable

import httpx
import pytest

from app.integrations import web
from app.models import City, Club, ClubKind
from app.services import club_enrichment
from app.services.contact_extraction import contact_page_links, extract_contacts

HOME = """
<html><body>
  <nav><a href="/contacto">Contacto</a> <a href="https://facebook.com/club">FB</a>
       <a href="https://other-site.com/contact">elsewhere</a></nav>
  <p>Club de Tenis Valencia — pistas de tierra batida.</p>
  <a href="https://playtomic.io/club-tenis-valencia">Reservar pista</a>
  <footer>Teléfono: 963 69 06 33 ·
    <a href="mailto:info@ctvalencia.es?subject=hola">Email</a></footer>
</body></html>
"""
CONTACT = '<html><body><a href="tel:+34963690633">Llámanos</a></body></html>'

# Captured at import, before the autouse "no network" stub replaces it for other tests.
REAL_FETCH_PAGES = web.fetch_pages


# --- Extraction (pure) ------------------------------------------------------------------


def test_extracts_phone_email_and_booking_link() -> None:
    contacts = extract_contacts(
        [("https://ctvalencia.es/", HOME), ("https://ctvalencia.es/contacto", CONTACT)], "ES"
    )
    assert contacts.phone == "+34 963 69 06 33"
    assert contacts.email == "info@ctvalencia.es"
    assert contacts.booking_url == "https://playtomic.io/club-tenis-valencia"


def test_phone_in_text_needs_a_nearby_keyword() -> None:
    html = "<p>Founded 1985. Members: 1200 4567 890.</p><p>Call us: (512) 555-0123</p>"
    assert extract_contacts([("https://c.example/", html)], "US").phone == "+1 512-555-0123"
    assert (
        extract_contacts([("https://c.example/", "<p>Founded 1985 1200 4567</p>")], "US").phone
        is None
    )


def test_booking_link_by_wording_when_no_platform() -> None:
    html = '<a href="/members">Members</a><a href="/book-a-court">Book a court</a>'
    contacts = extract_contacts([("https://club.example/", html)], "US")
    assert contacts.booking_url == "https://club.example/book-a-court"


def test_file_links_are_not_booking_pages() -> None:
    html = '<a href="/docs/reservas.pdf">Reservar pista</a>'
    assert extract_contacts([("https://ayto.example/", html)], "ES").booking_url is None


def test_osm_phone_lists_use_the_first_valid_number() -> None:
    from app.services.contact_extraction import parse_phone

    assert parse_phone("+359 88 750 0529;+359 87 840 8555", "BG") == "+359 88 750 0529"
    assert parse_phone("not a number; 963 28 91 40", "ES") == "+34 963 28 91 40"
    assert parse_phone("", "ES") is None


def test_contact_page_links_stay_on_site() -> None:
    assert contact_page_links(HOME, "https://www.ctvalencia.es/") == [
        "https://www.ctvalencia.es/contacto"
    ]


# --- Safe fetching ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/computeMetadata/v1/",  # cloud metadata server
        "http://[::1]/",
        "ftp://93.184.215.14/",
        "http://93.184.215.14:8080/",
        "file:///etc/passwd",
    ],
)
async def test_unsafe_urls_are_refused(url: str) -> None:
    with pytest.raises(web.FetchBlocked):
        await web._check_url(url)


def mock_site(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    monkeypatch.setattr(
        web,
        "_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False),
    )


async def test_redirect_into_a_private_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    mock_site(monkeypatch, handler)
    with pytest.raises(web.FetchBlocked):
        await REAL_FETCH_PAGES(["http://93.184.215.14/"])  # a public IP literal: no DNS needed


async def test_robots_txt_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    mock_site(monkeypatch, handler)
    with pytest.raises(web.FetchBlocked, match="robots"):
        await REAL_FETCH_PAGES(["http://93.184.215.14/"])


async def test_html_pages_are_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=HOME, headers={"content-type": "text/html; charset=utf-8"})

    mock_site(monkeypatch, handler)
    pages = await REAL_FETCH_PAGES(["http://93.184.215.14/"])
    assert "Reservar pista" in pages[0].html


# --- Enrichment -------------------------------------------------------------------------


class FakeOverpass:
    def __init__(self, tags: dict[str, dict[str, str]]) -> None:
        self.tags = tags
        self.calls: list[list[str]] = []

    async def fetch_tags(self, refs: list[str]) -> dict[str, dict[str, str]]:
        self.calls.append(refs)
        return {ref: self.tags[ref] for ref in refs if ref in self.tags}


class FakeSearch:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.queries: list[str] = []

    async def find(self, name: str, city: str, country_code: str) -> str | None:
        self.queries.append(name)
        return self.result


VALENCIA = City(name="Valencia", country_code="ES")


def club(name: str, kind: ClubKind, ref: str) -> Club:
    return Club(
        name=name,
        kind=kind,
        external_key=f"osm:{ref}",
        sources={"osm": [ref]},
        website=None,
        website_source=None,
    )


async def test_osm_website_is_crawled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(urls: list[str]) -> list[web.Page]:
        return [web.Page(urls[0], HOME if "contacto" not in urls[0] else CONTACT)]

    monkeypatch.setattr(web, "fetch_pages", fake_fetch)
    found = await club_enrichment.find_contacts(
        club("Club de Tenis Valencia", ClubKind.CLUB, "way/1"),
        {"website": "ctvalencia.es"},
        VALENCIA,
        search=None,
    )
    assert (found.website, found.website_source, found.status) == (
        "https://ctvalencia.es",
        "osm",
        "ok",
    )
    assert found.phone == "+34 963 69 06 33"
    assert found.booking_url == "https://playtomic.io/club-tenis-valencia"


async def test_search_finds_websites_for_named_clubs_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(urls: list[str]) -> list[web.Page]:
        return [web.Page(urls[0], "<a href='tel:+34960000000'>call</a>")]

    monkeypatch.setattr(web, "fetch_pages", fake_fetch)
    search = FakeSearch("https://found.example/")

    named = await club_enrichment.find_contacts(
        club("Valencia Tennis Center", ClubKind.SPORTS_CENTRE, "way/2"), {}, VALENCIA, search
    )
    generic = await club_enrichment.find_contacts(
        club("Tennis courts · Ruzafa", ClubKind.SPORTS_CENTRE, "way/3"), {}, VALENCIA, search
    )
    assert (named.website, named.website_source, named.phone) == (
        "https://found.example/",
        "search",
        "+34 960 00 00 00",
    )
    assert generic.status == "no_website"
    assert search.queries == ["Valencia Tennis Center"]


async def test_social_pages_are_not_treated_as_websites() -> None:
    found = await club_enrichment.find_contacts(
        club("Pista Club", ClubKind.CLUB, "way/4"),
        {"website": "https://www.facebook.com/pistaclub", "phone": "+34 961 23 45 67"},
        VALENCIA,
        search=None,
    )
    assert (found.website, found.phone, found.status) == (None, "+34 961 23 45 67", "osm_only")


async def test_unreachable_and_blocked_sites_keep_what_we_know(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def blocked(urls: list[str]) -> list[web.Page]:
        raise web.FetchBlocked("robots.txt disallows")

    monkeypatch.setattr(web, "fetch_pages", blocked)
    found = await club_enrichment.find_contacts(
        club("X Club", ClubKind.CLUB, "way/5"),
        {"website": "https://x.example", "phone": "963 11 22 33"},
        VALENCIA,
        search=None,
    )
    assert (found.website, found.phone, found.status) == (
        "https://x.example",
        "+34 963 11 22 33",
        "blocked",
    )


# --- Batches in the database ------------------------------------------------------------


async def test_batches_enrich_facilities_then_public_courts(
    make_client, geocoder, sources, deliver, monkeypatch: pytest.MonkeyPatch, publisher
) -> None:
    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from tests.test_clubs_api import discover

    client = await make_client("client")
    city = (await discover(client)).json()["city"]
    overpass = FakeOverpass(
        {
            "way/500": {"website": "https://atc.example", "phone": "512 555 0100"},
            "way/1": {"phone": "(512) 555-0199"},
        }
    )
    crawled: list[str] = []

    async def fake_fetch(urls: list[str]) -> list[web.Page]:
        crawled.extend(urls)
        return [web.Page(urls[0], '<a href="/reserve">Book a court</a>')]

    monkeypatch.setattr(web, "fetch_pages", fake_fetch)
    monkeypatch.setattr("app.events.handlers.club_contacts.get_overpass", lambda: overpass)
    monkeypatch.setattr("app.events.handlers.club_contacts.get_website_search", lambda: None)

    # Discovery queues enrichment; deliver until the city is done (batches re-queue themselves).
    delivered = await deliver()
    assert delivered.count("clubs.enrichment.requested") == 2  # facilities batch, then public

    async with get_sessionmaker()() as session:
        clubs = {
            c.name: c for c in await session.scalars(select(Club).where(Club.city_id == city["id"]))
        }
    centre = clubs["Austin Tennis Center"]
    assert (centre.website, centre.phone) == ("https://atc.example", "+1 512-555-0100")
    assert centre.booking_url == "https://atc.example/reserve"
    assert centre.contacts_status == "ok"
    public = clubs["Tennis courts"]
    assert public.contacts_status == "no_website" and public.contacts_checked_at is not None
    assert crawled == ["https://atc.example"]  # public courts aren't crawled without a website

    listed = (await client.get("/clubs", params={"city_id": city["id"]})).json()
    assert {c["name"]: c["booking_url"] for c in listed}[
        "Austin Tennis Center"
    ] == "https://atc.example/reserve"
