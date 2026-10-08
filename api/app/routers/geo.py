from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.deps import CurrentUser
from app.integrations.geo import Geocoder, GeoProviderError, ReverseGeocoded, get_geocoder

router = APIRouter(prefix="/geo", tags=["geo"])

GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]

# ~110 m grid: nearby users share lookups, which keeps us well inside Nominatim's
# 1 request/second policy. Small in-process LRU; a miss just costs one provider call.
_PRECISION = 3
_CACHE_SIZE = 2048
_cache: OrderedDict[tuple[float, float], ReverseGeocoded | None] = OrderedDict()


class ReverseOut(BaseModel):
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None


@router.get("/reverse", responses={404: {"description": "Nothing found here"}})
async def reverse_geocode(
    _: CurrentUser,
    geocoder: GeocoderDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
) -> ReverseOut:
    """City, region, postal code and country for a point (e.g. the browser's location)."""
    key = (round(lat, _PRECISION), round(lon, _PRECISION))
    if key in _cache:
        _cache.move_to_end(key)
        found = _cache[key]
    else:
        try:
            found = await geocoder.reverse(*key)
        except GeoProviderError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, "Location lookup is unavailable right now"
            ) from exc
        _cache[key] = found
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    if found is None or not found.city:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "We couldn't tell which city you're in")
    return ReverseOut(
        city=found.city,
        region=found.region,
        postal_code=found.postal_code,
        country_code=found.country_code,
    )
