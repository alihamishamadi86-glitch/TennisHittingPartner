import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep, require_roles
from app.events.outbox import commit_and_publish
from app.integrations.geo import Geocoder, GeoProviderError, get_geocoder
from app.models import City, Club, DiscoveryStatus, PartnerProfile, User, UserRole
from app.schemas.clubs import (
    CityDiscoverIn,
    CityOut,
    ClubOut,
    DiscoveryOut,
    FocusOut,
    PartnerClubsIn,
    PartnerClubsOut,
)
from app.services import clubs as club_service

router = APIRouter(tags=["clubs"])

GeocoderDep = Annotated[Geocoder, Depends(get_geocoder)]
PartnerUser = Annotated[User, Depends(require_roles(UserRole.PARTNER))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


def club_out(club: Club, distance_m: float | None = None) -> ClubOut:
    out = ClubOut.model_validate(club)
    out.distance_km = round(distance_m / 1000, 2) if distance_m is not None else None
    return out


@router.post("/cities/discover", responses={202: {"description": "Discovery queued"}})
async def discover_city(
    body: CityDiscoverIn,
    response: Response,
    _: CurrentUser,  # signed-in users only: lookups spend provider quota
    session: SessionDep,
    geocoder: GeocoderDep,
) -> DiscoveryOut:
    """Find (or start finding) tennis clubs and courts in a city. With a postal code, results
    are focused around it (its city is discovered). Poll GET /cities/{id} until `status` is
    `ready`, then list clubs near `focus` or in the city."""
    city_name, region, focus = body.city, body.region, None
    try:
        geocoded_now = False
        if body.postal_code:
            postcode, geocoded_now = await club_service.resolve_postcode(
                session, geocoder, body.postal_code, body.country_code
            )
            focus = postcode
            if postcode.city_name:  # the postcode's own city is more reliable than free text
                city_name, region = postcode.city_name, postcode.region
        if not city_name:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "We couldn't tell which city that postal code is in"
            )
        city = await club_service.request_discovery(
            session,
            geocoder,
            city=city_name,
            region=region,
            country_code=body.country_code,
            pause_before_geocode=geocoded_now,
        )
    except club_service.PostcodeNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "We couldn't find that postal code") from exc
    except club_service.CityNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "We couldn't find that city") from exc
    except GeoProviderError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Location search is unavailable right now"
        ) from exc
    if focus is not None:
        focus.city_id = city.id
    await commit_and_publish(session)
    if city.status is not DiscoveryStatus.READY:
        response.status_code = status.HTTP_202_ACCEPTED
    return DiscoveryOut(
        city=CityOut.model_validate(city),
        focus=FocusOut(postal_code=focus.postal_code, lat=focus.lat, lon=focus.lon)
        if focus
        else None,
    )


@router.get("/cities/{city_id}")
async def get_city(city_id: uuid.UUID, session: SessionDep) -> CityOut:
    city = await session.get(City, city_id)
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "City not found")
    return CityOut.model_validate(city)


@router.get("/clubs")
async def list_clubs(
    session: SessionDep,
    city_id: uuid.UUID | None = None,
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float, Query(gt=0, le=100)] = 25,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> list[ClubOut]:
    """Clubs in a city and/or near a point (sorted by distance when a point is given)."""
    if city_id is None and (lat is None or lon is None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give city_id or lat/lon")
    near = (lat, lon) if lat is not None and lon is not None else None
    rows = await club_service.list_clubs(
        session, city_id=city_id, near=near, radius_km=radius_km, query=q, limit=limit
    )
    return [club_out(club, distance) for club, distance in rows]


@router.get("/clubs/{club_id}")
async def get_club(club_id: uuid.UUID, session: SessionDep) -> ClubOut:
    club = await session.get(Club, club_id)
    if club is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Club not found")
    return club_out(club)


async def _partner_clubs_out(session: SessionDep, partner_id: uuid.UUID) -> PartnerClubsOut:
    ids = await club_service.partner_club_ids(session, partner_id)
    clubs = (await session.scalars(select(Club).where(Club.id.in_(ids)))).all() if ids else []
    return PartnerClubsOut(club_ids=ids, clubs=[club_out(c) for c in clubs])


@router.get("/me/partner-clubs")
async def get_partner_clubs(user: PartnerUser, session: SessionDep) -> PartnerClubsOut:
    return await _partner_clubs_out(session, user.id)


@router.put("/me/partner-clubs")
async def put_partner_clubs(
    body: PartnerClubsIn, user: PartnerUser, session: SessionDep
) -> PartnerClubsOut:
    """Replace the set of clubs this partner plays at."""
    if await session.get(PartnerProfile, user.id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your partner profile first")
    try:
        await club_service.set_partner_clubs(session, user, body.club_ids)
    except club_service.UnknownClubError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return await _partner_clubs_out(session, user.id)


@router.post("/admin/cities/{city_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_city(city_id: uuid.UUID, _: AdminUser, session: SessionDep) -> CityOut:
    city = await session.get(City, city_id)
    if city is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "City not found")
    club_service.queue_refresh(session, city)
    await commit_and_publish(session)
    return CityOut.model_validate(city)
