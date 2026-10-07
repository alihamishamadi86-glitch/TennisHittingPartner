"""Geocoding and tennis-place sources built on open data (OpenStreetMap).

- Geocoding: Geoapify (OSM-based, free tier) when an API key is configured, else Nominatim.
- Places: Overpass (OSM, tennis-specific tags) as primary; Geoapify Places as a secondary
  source that contributes formatted addresses. Both are OSM-derived, so results are merged by
  OSM id where possible.
"""

import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"


class GeoProviderError(Exception):
    """A provider failed (network, rate limit, bad response). Usually worth retrying."""


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    @classmethod
    def around(cls, lat: float, lon: float, radius_km: float) -> "BBox":
        dlat = radius_km / 111.32
        dlon = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
        return cls(lat - dlat, lon - dlon, lat + dlat, lon + dlon)


@dataclass(frozen=True)
class GeocodedCity:
    name: str
    region: str | None
    country_code: str
    lat: float
    lon: float
    bbox: BBox
    provider: str
    place_id: str | None = None


@dataclass(frozen=True)
class RawPlace:
    source: str  # "osm" | "geoapify"
    source_id: str  # e.g. "way/123" for OSM
    name: str | None
    lat: float
    lon: float
    tags: dict[str, str] = field(default_factory=dict)
    address: str | None = None
    # OSM element this place came from ("way/123"), when known — used to merge sources.
    osm_ref: str | None = None
    # Named park/school/campus used only to name nearby unnamed courts.
    landmark: bool = False


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers={"User-Agent": get_settings().geo_user_agent},
    )


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    try:
        response = await client.request(kwargs.pop("method", "GET"), url, **kwargs)
    except httpx.HTTPError as exc:
        raise GeoProviderError(f"{url}: {exc!r}") from exc
    if response.status_code >= 400:
        raise GeoProviderError(f"{url}: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise GeoProviderError(f"{url}: invalid JSON") from exc


def _bbox_or_radius(raw: Any, lat: float, lon: float) -> BBox:
    radius = get_settings().city_search_radius_km
    fallback = BBox.around(lat, lon, radius)
    if not raw:
        return fallback
    box = BBox(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    # Clamp huge administrative areas (e.g. a county-sized city) to a sensible search radius.
    return BBox(
        max(box.south, fallback.south),
        max(box.west, fallback.west),
        min(box.north, fallback.north),
        min(box.east, fallback.east),
    )


# --- Geocoders --------------------------------------------------------------------------


class Geocoder(Protocol):
    async def geocode_city(
        self, city: str, region: str | None, country_code: str
    ) -> GeocodedCity | None: ...


class GeoapifyGeocoder:
    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def geocode_city(
        self, city: str, region: str | None, country_code: str
    ) -> GeocodedCity | None:
        text = ", ".join(part for part in (city, region) if part)
        async with _http() as client:
            body = await _get_json(
                client,
                GEOAPIFY_GEOCODE_URL,
                params={
                    "text": text,
                    "type": "city",
                    "filter": f"countrycode:{country_code.lower()}",
                    "format": "json",
                    "limit": 1,
                    "lang": "en",
                    "apiKey": self._key,
                },
            )
        results = body.get("results") or []
        if not results:
            return None
        top = results[0]
        lat, lon = float(top["lat"]), float(top["lon"])
        raw_bbox = top.get("bbox")
        bbox = (
            [raw_bbox["lat1"], raw_bbox["lon1"], raw_bbox["lat2"], raw_bbox["lon2"]]
            if raw_bbox
            else None
        )
        return GeocodedCity(
            name=top.get("city") or top.get("name") or city,
            region=top.get("state_code") or top.get("state") or region,
            country_code=(top.get("country_code") or country_code).upper(),
            lat=lat,
            lon=lon,
            bbox=_bbox_or_radius(bbox, lat, lon),
            provider="geoapify",
            place_id=top.get("place_id"),
        )


class NominatimGeocoder:
    """Free OSM geocoder. Usage policy: ≤1 request/second with an identifying User-Agent —
    fine for interactive city lookups, which are cached in the `cities` table."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def geocode_city(
        self, city: str, region: str | None, country_code: str
    ) -> GeocodedCity | None:
        params: dict[str, Any] = {
            "city": city,
            "countrycodes": country_code.lower(),
            "format": "jsonv2",
            "addressdetails": 1,
            "limit": 1,
            "accept-language": "en",
        }
        if region:
            params["state"] = region
        async with _http() as client:
            results = await _get_json(client, f"{self._base}/search", params=params)
        if not results:
            return None
        top = results[0]
        address = top.get("address", {})
        lat, lon = float(top["lat"]), float(top["lon"])
        south, north, west, east = (float(v) for v in top["boundingbox"])
        return GeocodedCity(
            name=address.get("city")
            or address.get("town")
            or address.get("village")
            or top.get("name")
            or city,
            region=address.get("state") or region,
            country_code=(address.get("country_code") or country_code).upper(),
            lat=lat,
            lon=lon,
            bbox=_bbox_or_radius([south, west, north, east], lat, lon),
            provider="nominatim",
            place_id=f"{top.get('osm_type')}/{top.get('osm_id')}",
        )


# --- Place sources ----------------------------------------------------------------------


class PlaceSource(Protocol):
    name: str

    async def fetch(self, bbox: BBox) -> list[RawPlace]: ...


TENNIS = '"sport"~"(^|;)tennis(;|$)"'
LANDMARK_REACH_M = 200


def _area(bbox: BBox) -> str:
    return f"({bbox.south},{bbox.west},{bbox.north},{bbox.east})"


def overpass_query(bbox: BBox) -> str:
    area = _area(bbox)
    return f"""[out:json][timeout:25];
(
  nwr["leisure"="pitch"][{TENNIS}]{area};
  nwr["leisure"~"^(sports_centre|sports_hall|stadium|club)$"][{TENNIS}]{area};
  nwr["club"~"^(sport|tennis)$"][{TENNIS}]{area};
);
out center tags;"""


def landmark_query(bbox: BBox) -> str:
    """Names for unnamed courts: parks/schools/campuses within reach of a court (`around`
    keeps this small), plus neighbourhood names as a coarser fallback."""
    area = _area(bbox)
    return f"""[out:json][timeout:60];
nwr["leisure"="pitch"][{TENNIS}]{area}->.courts;
(
  wr(around.courts:{LANDMARK_REACH_M})["leisure"~"^(park|recreation_ground)$"]["name"];
  wr(around.courts:{LANDMARK_REACH_M})["amenity"~"^(school|college|university)$"]["name"];
  node["place"~"^(neighbourhood|suburb|quarter)$"]["name"]{area};
);
out center tags;"""


def _is_tennis_tags(tags: dict[str, str]) -> bool:
    return "tennis" in tags.get("sport", "").lower()


class OverpassSource:
    name = "osm"

    def __init__(self, urls: list[str]) -> None:
        self._urls = urls

    async def _run(self, client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
        """Try each Overpass instance in turn; public instances often return 429/504."""
        errors = []
        for url in self._urls:
            try:
                body = await _get_json(client, url, method="POST", data={"data": query})
            except GeoProviderError as exc:
                errors.append(str(exc))
                continue
            elements: list[dict[str, Any]] = body.get("elements", [])
            return elements
        raise GeoProviderError("; ".join(errors) or "no Overpass instances configured")

    async def fetch(self, bbox: BBox) -> list[RawPlace]:
        async with _http() as client:
            elements = await self._run(client, overpass_query(bbox))
            try:
                elements += await self._run(client, landmark_query(bbox))
            except GeoProviderError as exc:
                # Optional: courts are still found, just with generic names.
                logger.warning("Overpass landmark lookup failed: %s", exc)

        places = []
        for element in elements:
            point = element.get("center") or element
            if "lat" not in point:
                continue
            ref = f"{element['type']}/{element['id']}"
            tags = {str(k): str(v) for k, v in (element.get("tags") or {}).items()}
            places.append(
                RawPlace(
                    source="osm",
                    source_id=ref,
                    name=tags.get("name"),
                    lat=float(point["lat"]),
                    lon=float(point["lon"]),
                    tags=tags,
                    address=osm_address(tags),
                    osm_ref=ref,
                    landmark=not _is_tennis_tags(tags),
                )
            )
        return places


def _is_tennis(name: str | None, tags: dict[str, str]) -> bool:
    return _is_tennis_tags(tags) or "tennis" in (name or "").lower()


def osm_address(tags: dict[str, str]) -> str | None:
    street = tags.get("addr:street")
    if not street:
        return None
    line = " ".join(p for p in (tags.get("addr:housenumber"), street) if p)
    city = ", ".join(p for p in (tags.get("addr:city"), tags.get("addr:state")) if p)
    return f"{line}, {city}" if city else line


class GeoapifyPlacesSource:
    """Geoapify has no tennis category; fetch pitches/sports centres and keep tennis ones."""

    name = "geoapify"
    PAGE_SIZE = 500

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    async def fetch(self, bbox: BBox) -> list[RawPlace]:
        async with _http() as client:
            body = await _get_json(
                client,
                GEOAPIFY_PLACES_URL,
                params={
                    "categories": "sport.pitch,sport.sports_centre,sport.sports_hall",
                    "filter": f"rect:{bbox.west},{bbox.south},{bbox.east},{bbox.north}",
                    "limit": self.PAGE_SIZE,
                    "lang": "en",
                    "apiKey": self._key,
                },
            )
        places = []
        for feature in body.get("features", []):
            props = feature.get("properties", {})
            raw = (props.get("datasource") or {}).get("raw") or {}
            tags = {str(k): str(v) for k, v in raw.items() if isinstance(v, str | int | float)}
            name = props.get("name")
            if not _is_tennis(name, tags):
                continue
            osm_ref = None
            if "osm_type" in raw and "osm_id" in raw:
                osm_type = {"n": "node", "w": "way", "r": "relation"}.get(
                    str(raw["osm_type"]), str(raw["osm_type"])
                )
                osm_ref = f"{osm_type}/{abs(int(raw['osm_id']))}"
            places.append(
                RawPlace(
                    source="geoapify",
                    source_id=str(props.get("place_id")),
                    name=name,
                    lat=float(props["lat"]),
                    lon=float(props["lon"]),
                    tags=tags,
                    address=props.get("formatted"),
                    osm_ref=osm_ref,
                )
            )
        return places


@lru_cache
def get_geocoder() -> Geocoder:
    settings = get_settings()
    key = settings.geoapify_api_key.get_secret_value().strip()
    return GeoapifyGeocoder(key) if key else NominatimGeocoder(settings.nominatim_url)


@lru_cache
def get_place_sources() -> tuple[PlaceSource, ...]:
    settings = get_settings()
    key = settings.geoapify_api_key.get_secret_value().strip()
    sources: list[PlaceSource] = [OverpassSource(settings.overpass_urls)]
    if key:
        sources.append(GeoapifyPlacesSource(key))
    return tuple(sources)
