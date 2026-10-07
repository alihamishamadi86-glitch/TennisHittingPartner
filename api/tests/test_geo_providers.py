from collections.abc import Callable

import httpx
import pytest

from app.integrations import geo
from app.integrations.geo import (
    BBox,
    GeoapifyGeocoder,
    GeoapifyPlacesSource,
    GeoProviderError,
    NominatimGeocoder,
    OverpassSource,
    overpass_query,
)

BOX = BBox(30.1, -97.9, 30.5, -97.5)


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


async def test_overpass_parses_tennis_places_and_landmarks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tennis = [
        {"type": "node", "id": 1, "lat": 30.2, "lon": -97.7, "tags": {"sport": "tennis"}},
        {
            "type": "way",
            "id": 2,
            "center": {"lat": 30.3, "lon": -97.6},
            "tags": {"leisure": "pitch", "sport": "tennis;basketball", "name": "Courts"},
        },
        {"type": "relation", "id": 3, "tags": {}},  # no geometry → skipped
    ]
    landmarks = [
        {
            "type": "way",
            "id": 4,
            "center": {"lat": 30.31, "lon": -97.61},
            "tags": {"leisure": "park", "name": "Zilker Park"},
        }
    ]
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = landmarks if b"park" in request.content else tennis
        return httpx.Response(200, json={"elements": body})

    monkeypatch.setattr(
        geo, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    places = await OverpassSource(["https://overpass.example/api"]).fetch(BOX)

    assert [(p.source_id, p.name, p.landmark) for p in places] == [
        ("node/1", None, False),
        ("way/2", "Courts", False),
        ("way/4", "Zilker Park", True),
    ]
    assert places[1].osm_ref == "way/2"
    assert [r.method for r in seen] == ["POST", "POST"]


def test_osm_address_from_tags() -> None:
    from app.integrations.geo import osm_address

    assert (
        osm_address(
            {"addr:housenumber": "7800", "addr:street": "Johnny Morris Rd", "addr:city": "Austin"}
        )
        == "7800 Johnny Morris Rd, Austin"
    )
    assert osm_address({"addr:city": "Austin"}) is None


def test_overpass_query_targets_tennis_in_bbox() -> None:
    query = overpass_query(BOX)
    assert '"leisure"="pitch"' in query
    assert "(30.1,-97.9,30.5,-97.5)" in query
    assert "out center tags" in query


async def test_geoapify_places_keeps_only_tennis(respond) -> None:
    def feature(name: str, raw: dict) -> dict:
        return {
            "properties": {
                "name": name,
                "place_id": f"id-{name}",
                "lat": 30.2,
                "lon": -97.7,
                "formatted": f"{name}, Austin",
                "datasource": {"raw": raw},
            }
        }

    seen = respond(
        {
            "features": [
                feature("Soccer Field", {"sport": "soccer", "osm_type": "w", "osm_id": 1}),
                feature("Riverside Courts", {"sport": "tennis", "osm_type": "w", "osm_id": 2}),
                feature("Austin Tennis Academy", {}),
            ]
        }
    )

    places = await GeoapifyPlacesSource("key").fetch(BOX)

    assert [p.name for p in places] == ["Riverside Courts", "Austin Tennis Academy"]
    assert places[0].osm_ref == "way/2"
    assert places[0].address == "Riverside Courts, Austin"
    assert seen[0].url.params["filter"] == "rect:-97.9,30.1,-97.5,30.5"


async def test_nominatim_geocodes_city(respond) -> None:
    respond(
        [
            {
                "lat": "30.2711",
                "lon": "-97.7437",
                "boundingbox": ["30.09", "30.52", "-97.94", "-97.56"],
                "osm_type": "relation",
                "osm_id": 113314,
                "address": {"city": "Austin", "state": "Texas", "country_code": "us"},
            }
        ]
    )

    city = await NominatimGeocoder("https://nominatim.example").geocode_city("austin", "TX", "US")

    assert city is not None
    assert (city.name, city.region, city.country_code) == ("Austin", "Texas", "US")
    # Nominatim's box, clamped to the 20 km search radius around the centre
    assert 30.09 <= city.bbox.south < 30.1
    assert city.provider == "nominatim"


async def test_geoapify_geocoder_falls_back_to_radius_bbox(respond) -> None:
    seen = respond(
        {
            "results": [
                {
                    "city": "Austin",
                    "state": "Texas",
                    "state_code": "TX",
                    "country_code": "us",
                    "lat": 30.27,
                    "lon": -97.74,
                    "place_id": "geo-1",
                }
            ]
        }
    )

    city = await GeoapifyGeocoder("key").geocode_city("Austin", None, "US")

    assert city is not None
    assert (city.name, city.region, city.place_id) == ("Austin", "TX", "geo-1")
    assert city.bbox.south < 30.27 < city.bbox.north
    assert seen[0].url.params["filter"] == "countrycode:us"


async def test_huge_bounding_boxes_are_clamped(respond) -> None:
    respond(
        [
            {
                "lat": "30.0",
                "lon": "-97.0",
                "boundingbox": ["20", "40", "-110", "-80"],
                "address": {"city": "Sprawl"},
            }
        ]
    )
    city = await NominatimGeocoder("https://n.example").geocode_city("Sprawl", None, "US")
    assert city is not None
    assert city.bbox.north - city.bbox.south < 0.5


async def test_empty_geocode_returns_none(respond) -> None:
    respond({"results": []})
    assert await GeoapifyGeocoder("key").geocode_city("Nowhere", None, "US") is None


async def test_http_errors_raise_provider_error(respond) -> None:
    respond({"error": "rate limited"}, status=429)
    with pytest.raises(GeoProviderError, match="429"):
        await OverpassSource(["https://overpass.example/api"]).fetch(BOX)


async def test_overpass_falls_back_to_next_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        if request.url.host == "busy.example":
            return httpx.Response(504)
        return httpx.Response(200, json={"elements": []})

    monkeypatch.setattr(
        geo, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    source = OverpassSource(["https://busy.example/api", "https://ok.example/api"])

    assert await source.fetch(BOX) == []
    assert hosts[:2] == ["busy.example", "ok.example"]


async def test_landmark_failure_does_not_fail_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if b"park" in request.content:
            return httpx.Response(504)
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 30.2,
                        "lon": -97.7,
                        "tags": {"sport": "tennis"},
                    }
                ]
            },
        )

    monkeypatch.setattr(
        geo, "_http", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    places = await OverpassSource(["https://ok.example/api"]).fetch(BOX)
    assert [p.source_id for p in places] == ["node/1"]


async def test_nominatim_geocodes_postcode(respond) -> None:
    seen = respond(
        [
            {
                "lat": "39.4464830",
                "lon": "-0.3597425",
                "address": {
                    "postcode": "46013",
                    "city": "Valencia",
                    "state": "Valencian Community",
                },
            }
        ]
    )

    found = await NominatimGeocoder("https://n.example").geocode_postcode("46013", "ES")

    assert found is not None
    assert (found.city, found.region, found.lat) == ("Valencia", "Valencian Community", 39.446483)
    assert seen[0].url.params["postalcode"] == "46013"
    assert seen[0].url.params["countrycodes"] == "es"


async def test_geoapify_geocodes_postcode(respond) -> None:
    seen = respond(
        {"results": [{"lat": 51.501, "lon": -0.141, "city": "London", "state": "England"}]}
    )

    found = await GeoapifyGeocoder("key").geocode_postcode("SW1A 1AA", "GB")

    assert found is not None
    assert (found.city, found.country_code) == ("London", "GB")
    assert seen[0].url.params["type"] == "postcode"
