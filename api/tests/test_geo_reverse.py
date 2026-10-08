from collections.abc import Awaitable, Callable, Iterator

import pytest
from httpx import AsyncClient

from app.integrations.geo import GeoapifyGeocoder, GeoProviderError, NominatimGeocoder
from app.routers import geo as geo_router
from tests.geo_fixtures import FakeGeocoder

MakeClient = Callable[..., Awaitable[AsyncClient]]


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    geo_router._cache.clear()
    yield
    geo_router._cache.clear()


async def test_reverse_returns_address_parts(
    make_client: MakeClient, geocoder: FakeGeocoder
) -> None:
    client = await make_client("client")
    response = await client.get("/geo/reverse", params={"lat": 30.2672, "lon": -97.7431})
    assert response.status_code == 200
    assert response.json() == {
        "city": "Austin",
        "region": "Texas",
        "postal_code": "78701",
        "country_code": "US",
    }


async def test_nearby_points_share_a_cached_lookup(
    make_client: MakeClient, geocoder: FakeGeocoder
) -> None:
    client = await make_client("client")
    await client.get("/geo/reverse", params={"lat": 30.26721, "lon": -97.74312})
    await client.get("/geo/reverse", params={"lat": 30.26724, "lon": -97.74309})  # same ~110 m cell
    reverse_calls = [c for c in geocoder.calls if c[0] == "reverse"]
    assert reverse_calls == [("reverse", "30.267,-97.743", "")]  # rounded before the provider


async def test_reverse_errors(
    make_client: MakeClient, geocoder: FakeGeocoder, api_client: AsyncClient
) -> None:
    client = await make_client("client")
    params = {"lat": 0.0, "lon": 0.0}
    geocoder.reversed = None
    assert (await client.get("/geo/reverse", params=params)).status_code == 404
    geo_router._cache.clear()
    geocoder.error = GeoProviderError("down")
    assert (await client.get("/geo/reverse", params=params)).status_code == 503
    assert (await api_client.get("/geo/reverse", params=params)).status_code == 401
    assert (await client.get("/geo/reverse", params={"lat": 91, "lon": 0})).status_code == 422


async def test_nominatim_reverse(respond) -> None:
    seen = respond(
        {
            "address": {
                "road": "Carretera de la Font d'en Corts",
                "suburb": "Quatre Carreres",
                "city": "Valencia",
                "state": "Valencian Community",
                "postcode": "46013",
                "country_code": "es",
            }
        }
    )
    found = await NominatimGeocoder("https://n.example").reverse(39.4465, -0.3597)
    assert found is not None
    assert (found.city, found.region, found.postal_code, found.country_code) == (
        "Valencia",
        "Valencian Community",
        "46013",
        "ES",
    )
    assert seen[0].url.path == "/reverse"


async def test_nominatim_reverse_over_water_finds_nothing(respond) -> None:
    respond({"error": "Unable to geocode"})
    assert await NominatimGeocoder("https://n.example").reverse(0.0, 0.0) is None


async def test_geoapify_reverse_uses_town_when_no_city(respond) -> None:
    respond(
        {
            "results": [
                {"town": "Leander", "state": "Texas", "postcode": "78641", "country_code": "us"}
            ]
        }
    )
    found = await GeoapifyGeocoder("key").reverse(30.57, -97.85)
    assert found is not None
    assert (found.city, found.country_code) == ("Leander", "US")
