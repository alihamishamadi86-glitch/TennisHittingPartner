"""Fake geocoder and place sources for club discovery tests (registered in conftest)."""

from collections.abc import Callable, Iterator

import httpx
import pytest

from app.integrations import geo
from app.integrations.geo import (
    BBox,
    GeocodedCity,
    GeocodedPostcode,
    RawPlace,
    ReverseGeocoded,
    get_geocoder,
)
from tests.test_club_merge import BASE_LAT, BASE_LON, court, facility

AUSTIN = GeocodedCity(
    name="Austin",
    region="TX",
    country_code="US",
    lat=BASE_LAT,
    lon=BASE_LON,
    bbox=BBox.around(BASE_LAT, BASE_LON, 20),
    provider="fake",
)


class FakeGeocoder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, str]] = []
        self.result: GeocodedCity | None = AUSTIN
        self.error: Exception | None = None
        self.unknown_regions: set[str] = set()
        self.reversed: ReverseGeocoded | None = ReverseGeocoded("Austin", "Texas", "78701", "US")
        self.postcodes: dict[str, GeocodedPostcode] = {
            # ~2.2 km north of downtown, next to the northern public courts in PLACES
            "78751": GeocodedPostcode("78751", "US", BASE_LAT + 0.02, BASE_LON, "Austin", "TX"),
            "00000": GeocodedPostcode("00000", "US", 1.0, 1.0, None, None),
        }

    async def geocode_city(self, city: str, region: str | None, country_code: str):  # type: ignore[no-untyped-def]
        self.calls.append((city, region, country_code))
        if self.error:
            raise self.error
        if region in self.unknown_regions:
            return None
        return self.result

    async def geocode_postcode(self, postal_code: str, country_code: str):  # type: ignore[no-untyped-def]
        self.calls.append(("postcode", postal_code, country_code))
        if self.error:
            raise self.error
        return self.postcodes.get(postal_code)

    async def reverse(self, lat: float, lon: float):  # type: ignore[no-untyped-def]
        self.calls.append(("reverse", f"{lat},{lon}", ""))
        if self.error:
            raise self.error
        return self.reversed


class FakeSource:
    def __init__(self, name: str, places: list[RawPlace]) -> None:
        self.name = name
        self.places = places
        self.error: Exception | None = None

    async def fetch(self, bbox: BBox) -> list[RawPlace]:
        if self.error:
            raise self.error
        return self.places


PLACES = [
    facility(500, "Austin Tennis Center", club="sport"),
    *[court(i, dlat=0.0002 * i) for i in range(1, 4)],
    *[court(i, dlat=0.02 + 0.0002 * i) for i in range(10, 12)],  # ~2.2 km north
]


@pytest.fixture
def geocoder() -> Iterator[FakeGeocoder]:
    from app.main import app

    fake = FakeGeocoder()
    app.dependency_overrides[get_geocoder] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_geocoder, None)


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> list[FakeSource]:
    fakes = [FakeSource("osm", PLACES), FakeSource("geoapify", [])]
    monkeypatch.setattr("app.events.handlers.clubs.get_place_sources", lambda: tuple(fakes))
    return fakes


@pytest.fixture
def respond(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Route provider HTTP calls to a canned response; returns the captured requests."""

    def install(body: object, status: int = 200) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(status, json=body)

        monkeypatch.setattr(
            geo, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )
        return seen

    return install
