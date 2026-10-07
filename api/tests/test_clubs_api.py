from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.events.envelope import EventEnvelope
from app.events.publisher import InMemoryPublisher
from app.events.registry import dispatch
from app.integrations.geo import BBox, GeocodedCity, GeoProviderError, RawPlace, get_geocoder
from app.models import City
from tests.test_club_merge import BASE_LAT, BASE_LON, court, facility
from tests.test_profiles import PARTNER_PROFILE

MakeClient = Callable[..., Awaitable[AsyncClient]]

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

    async def geocode_city(self, city: str, region: str | None, country_code: str):  # type: ignore[no-untyped-def]
        self.calls.append((city, region, country_code))
        if self.error:
            raise self.error
        if region in self.unknown_regions:
            return None
        return self.result


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


async def discover(client: AsyncClient, city: str = "austin", region: str = "tx"):  # type: ignore[no-untyped-def]
    return await client.post(
        "/cities/discover", json={"city": city, "region": region, "country_code": "US"}
    )


async def deliver_one(publisher: InMemoryPublisher) -> None:
    _, data, _ = publisher.messages.pop(0)
    await dispatch(get_sessionmaker(), EventEnvelope.model_validate_json(data))


async def test_discovery_finds_and_groups_clubs(
    make_client: MakeClient, geocoder: FakeGeocoder, sources, deliver
) -> None:
    client = await make_client("client")
    await deliver()  # registration events

    queued = await discover(client)

    assert queued.status_code == 202
    city = queued.json()
    assert (city["name"], city["status"]) == ("Austin", "pending")
    assert await deliver() == ["clubs.discovery.requested"]

    ready = (await client.get(f"/cities/{city['id']}")).json()
    assert ready["status"] == "ready"
    assert ready["club_count"] == 2

    clubs = (await client.get("/clubs", params={"city_id": city["id"]})).json()
    assert [(c["name"], c["kind"], c["court_count"]) for c in clubs] == [
        ("Austin Tennis Center", "club", 3),
        ("Tennis courts", "public_courts", 2),
    ]


async def test_repeat_lookup_uses_cache(
    make_client: MakeClient, geocoder: FakeGeocoder, sources, deliver, publisher
) -> None:
    client = await make_client("client")
    await discover(client)
    await deliver()

    again = await discover(client, city="Austin", region="TX")  # same normalized alias

    assert again.status_code == 200
    assert again.json()["status"] == "ready"
    assert len(geocoder.calls) == 1
    assert publisher.messages == []


async def test_different_spelling_resolving_to_same_city_reuses_it(
    make_client: MakeClient, geocoder: FakeGeocoder, sources, deliver, publisher
) -> None:
    client = await make_client("client")
    first = (await discover(client, region="tx")).json()
    await deliver()

    second = await discover(client, region="Texas")

    assert second.json()["id"] == first["id"]
    assert len(geocoder.calls) == 2  # new alias needs one geocode, then it's cached
    assert publisher.messages == []


async def test_clubs_near_point_sorted_by_distance(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    await discover(client)
    await deliver()

    near_north = await client.get(
        "/clubs", params={"lat": BASE_LAT + 0.02, "lon": BASE_LON, "radius_km": 5}
    )
    tight = await client.get(
        "/clubs", params={"lat": BASE_LAT + 0.02, "lon": BASE_LON, "radius_km": 1}
    )

    names = [(c["name"], c["distance_km"]) for c in near_north.json()]
    assert names[0][0] == "Tennis courts"
    assert names[0][1] < names[1][1]
    assert [c["name"] for c in tight.json()] == ["Tennis courts"]
    assert (await client.get("/clubs")).status_code == 422


async def test_unmatched_region_falls_back_to_city_and_country(
    make_client: MakeClient, geocoder: FakeGeocoder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.services.clubs.GEOCODER_RETRY_DELAY_S", 0)
    client = await make_client("client")
    geocoder.unknown_regions = {"46013"}  # a postcode typed into the region field

    response = await discover(client, city="Valencia", region="46013")

    assert response.status_code == 202
    assert [region for _, region, _ in geocoder.calls] == ["46013", None]


async def test_discovery_requires_sign_in(api_client: AsyncClient, geocoder) -> None:
    assert (await discover(api_client)).status_code == 401


async def test_unknown_city_and_provider_outage(make_client: MakeClient, geocoder) -> None:
    client = await make_client("client")
    geocoder.result = None
    assert (await discover(client, city="Atlantis")).status_code == 404
    geocoder.error = GeoProviderError("down")
    assert (await discover(client, city="Elsewhere")).status_code == 503


async def test_partial_source_failure_still_succeeds(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    sources[1].error = GeoProviderError("geoapify: HTTP 500")
    city = (await discover(client)).json()
    await deliver()

    async with get_sessionmaker()() as session:
        stored = await session.get(City, city["id"])
        assert stored is not None
        assert stored.status.value == "ready"
        assert stored.last_error and "geoapify" in stored.last_error


async def test_total_failure_retries_then_fails(
    make_client: MakeClient, geocoder, sources, deliver, publisher
) -> None:
    client = await make_client("client")
    await deliver()
    for source in sources:
        source.error = GeoProviderError("down")
    city = (await discover(client)).json()
    message = publisher.messages[0]

    for attempt in range(1, get_settings().discovery_max_attempts):
        publisher.messages[:] = [message]
        with pytest.raises(GeoProviderError):
            await deliver_one(publisher)  # Pub/Sub would redeliver
        state = (await client.get(f"/cities/{city['id']}")).json()["status"]
        assert state == "pending", attempt

    publisher.messages[:] = [message]
    await deliver_one(publisher)  # the last attempt gives up without raising
    assert (await client.get(f"/cities/{city['id']}")).json()["status"] == "failed"

    # Asking again after a failure re-queues it.
    for source in sources:
        source.error = None
    retried = await discover(client)
    assert retried.json()["status"] == "pending"
    await deliver()
    assert (await client.get(f"/cities/{city['id']}")).json()["status"] == "ready"


async def test_rediscovery_updates_and_hides_vanished_clubs(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    admin = await make_client("admin", admin=True)
    city = (await discover(admin)).json()
    await deliver()

    sources[0].places = PLACES[:4]  # the northern courts disappeared from OSM
    assert (await admin.post(f"/admin/cities/{city['id']}/refresh")).status_code == 202
    await deliver()

    clubs = (await admin.get("/clubs", params={"city_id": city["id"]})).json()
    assert [c["name"] for c in clubs] == ["Austin Tennis Center"]


async def test_stale_cities_are_refreshed_by_scheduled_task(
    make_client: MakeClient, geocoder, sources, deliver, worker_client: AsyncClient
) -> None:
    client = await make_client("client")
    city = (await discover(client)).json()
    await deliver()
    async with get_sessionmaker()() as session:
        await session.execute(
            update(City).values(discovered_at=datetime.now(UTC) - timedelta(days=45))
        )
        await session.commit()

    queued = await worker_client.post("/tasks/refresh-cities")

    assert queued.json() == {"queued": 1}
    assert await deliver() == ["clubs.discovery.requested"]
    assert (await client.get(f"/cities/{city['id']}")).json()["status"] == "ready"


# --- Partner clubs ----------------------------------------------------------------------


async def test_partner_selects_clubs(make_client: MakeClient, geocoder, sources, deliver) -> None:
    partner = await make_client("partner")
    city = (await discover(partner)).json()
    await deliver()
    club_ids = [
        c["id"] for c in (await partner.get("/clubs", params={"city_id": city["id"]})).json()
    ]

    no_profile = await partner.put("/me/partner-clubs", json={"club_ids": club_ids})
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    saved = await partner.put("/me/partner-clubs", json={"club_ids": club_ids})
    unknown = await partner.put(
        "/me/partner-clubs", json={"club_ids": ["00000000-0000-0000-0000-000000000000"]}
    )
    cleared = await partner.put("/me/partner-clubs", json={"club_ids": [club_ids[0]]})

    assert no_profile.status_code == 409
    assert saved.status_code == 200
    assert sorted(saved.json()["club_ids"]) == sorted(club_ids)
    assert unknown.status_code == 422
    assert [c["id"] for c in cleared.json()["clubs"]] == [club_ids[0]]
    assert (await partner.get("/me/partner-clubs")).json()["club_ids"] == [club_ids[0]]


async def test_only_partners_have_clubs(make_client: MakeClient) -> None:
    client = await make_client("client")
    assert (await client.get("/me/partner-clubs")).status_code == 403
