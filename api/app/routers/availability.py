import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.core.config import get_settings
from app.core.deps import CurrentUser, SessionDep, require_roles
from app.models import PartnerProfile, PartnerStatus, User, UserRole
from app.schemas.availability import (
    AvailabilityOut,
    ClubRefOut,
    DaySlotsOut,
    ExceptionIn,
    ExceptionOut,
    PartnerCardOut,
    PartnerPublicOut,
    SlotsOut,
    WeeklyScheduleIn,
    WeeklyWindowIn,
)
from app.services import availability as service
from app.services.slots import group_by_local_date

router = APIRouter(tags=["availability"])

PartnerUser = Annotated[User, Depends(require_roles(UserRole.PARTNER))]
Duration = Annotated[int, Query(description="Session length in minutes (60 or 90)")]


def _check_duration(duration: int) -> None:
    if duration not in get_settings().session_durations_minutes:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Duration must be one of {get_settings().session_durations_minutes}",
        )


async def _own_profile(session: SessionDep, user: User) -> PartnerProfile:
    profile = await session.get(PartnerProfile, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Create your partner profile first")
    return profile


async def _availability_out(session: SessionDep, profile: PartnerProfile) -> AvailabilityOut:
    tz = service.parse_timezone(profile.timezone or "UTC")
    today = datetime.now(UTC).astimezone(tz).date()
    rules = await service.list_rules(session, profile.user_id)
    exceptions = await service.list_upcoming_exceptions(session, profile.user_id, today)
    return AvailabilityOut(
        timezone=profile.timezone,
        windows=[
            WeeklyWindowIn(weekday=r.weekday, start=r.start_minute, end=r.end_minute) for r in rules
        ],
        exceptions=[
            ExceptionOut(
                id=e.id,
                date=e.date,
                kind=e.kind,
                start=e.start_minute,
                end=e.end_minute,
                note=e.note,
            )
            for e in exceptions
        ],
    )


def _slots_out(
    schedule: service.PartnerSchedule, tz_name: str, start: date, days: int, duration: int
) -> SlotsOut:
    last = start + timedelta(days=days - 1)
    slots = service.slots_for(schedule, start, last, duration, datetime.now(UTC))
    grouped = group_by_local_date(slots, schedule.tz)
    return SlotsOut(
        timezone=tz_name,
        duration_minutes=duration,
        days=[
            DaySlotsOut(
                date=start + timedelta(days=i), slots=grouped.get(start + timedelta(days=i), [])
            )
            for i in range(days)
        ],
    )


# --- Partner: manage own availability ---------------------------------------------------


@router.get("/me/availability")
async def get_my_availability(user: PartnerUser, session: SessionDep) -> AvailabilityOut:
    return await _availability_out(session, await _own_profile(session, user))


@router.put("/me/availability")
async def put_my_availability(
    body: WeeklyScheduleIn, user: PartnerUser, session: SessionDep
) -> AvailabilityOut:
    """Replace the weekly schedule (and set the timezone it's expressed in)."""
    profile = await _own_profile(session, user)
    try:
        await service.replace_weekly_schedule(
            session, profile, body.timezone, [(w.weekday, w.start, w.end) for w in body.windows]
        )
    except service.AvailabilityError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return await _availability_out(session, profile)


@router.post("/me/availability/exceptions", status_code=status.HTTP_201_CREATED)
async def add_my_exception(
    body: ExceptionIn, user: PartnerUser, session: SessionDep
) -> AvailabilityOut:
    profile = await _own_profile(session, user)
    if profile.timezone is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set your weekly schedule first")
    try:
        await service.add_exception(
            session,
            profile,
            day=body.date,
            kind=body.kind,
            start=body.start,
            end=body.end,
            note=body.note,
        )
    except service.AvailabilityError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return await _availability_out(session, profile)


@router.delete("/me/availability/exceptions/{exception_id}", status_code=204)
async def delete_my_exception(
    exception_id: uuid.UUID, user: PartnerUser, session: SessionDep
) -> Response:
    if not await service.delete_exception(session, user.id, exception_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await session.commit()
    return Response(status_code=204)


@router.get("/me/availability/preview")
async def preview_my_slots(
    user: PartnerUser,
    session: SessionDep,
    duration: Duration = 60,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
) -> SlotsOut:
    """What clients will see: bookable start times for the coming days."""
    _check_duration(duration)
    profile = await _own_profile(session, user)
    if profile.timezone is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Set your weekly schedule first")
    today = datetime.now(UTC).astimezone(service.parse_timezone(profile.timezone)).date()
    schedule = (
        await service.load_schedules(session, [profile], today, today + timedelta(days=days))
    )[user.id]
    return _slots_out(schedule, profile.timezone, today, days, duration)


# --- Clients: search and partner pages --------------------------------------------------


@router.get("/partners/search")
async def search_partners(
    _: CurrentUser,
    session: SessionDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=100)] = 15,
    on: Annotated[date | None, Query(alias="date")] = None,
    duration: Duration = 60,
    min_level: Annotated[Decimal | None, Query(ge=1.5, le=7.0)] = None,
    club_id: uuid.UUID | None = None,
) -> list[PartnerCardOut]:
    """Approved partners who play near the point. With `date`, `slots` lists that day's
    bookable start times; `next_slot` is the soonest one in the next two weeks."""
    _check_duration(duration)
    matches = await service.search_partners(
        session,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        day=on,
        duration_minutes=duration,
        min_level=min_level,
        club_id=club_id,
    )
    return [
        PartnerCardOut(
            user_id=m.user.id,
            full_name=m.user.full_name,
            avatar_url=m.user.avatar_url,
            ntrp_rating=m.profile.verified_ntrp_rating,
            background=m.profile.background,
            play_style=m.profile.play_style,
            years_playing=m.profile.years_playing,
            bio=m.profile.bio[:280],
            timezone=m.profile.timezone or "UTC",
            distance_km=round(m.distance_m / 1000, 1),
            clubs=[
                ClubRefOut(id=c.id, name=c.name, distance_km=round(c.distance_m / 1000, 1))
                for c in m.clubs
            ],
            slots=m.slots,
            next_slot=m.next_slot,
        )
        for m in matches
    ]


async def _approved_partner(
    session: SessionDep, partner_id: uuid.UUID
) -> tuple[PartnerProfile, User]:
    profile = await session.get(PartnerProfile, partner_id)
    user = await session.get(User, partner_id)
    if (
        profile is None
        or user is None
        or not user.is_active
        or profile.status is not PartnerStatus.APPROVED
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partner not found")
    return profile, user


@router.get("/partners/{partner_id}")
async def get_partner(
    partner_id: uuid.UUID, _: CurrentUser, session: SessionDep
) -> PartnerPublicOut:
    profile, user = await _approved_partner(session, partner_id)
    clubs = await service.partner_clubs(session, partner_id)
    return PartnerPublicOut(
        user_id=user.id,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        ntrp_rating=profile.verified_ntrp_rating,
        background=profile.background,
        play_style=profile.play_style,
        dominant_hand=profile.dominant_hand,
        years_playing=profile.years_playing,
        bio=profile.bio,
        city=profile.city,
        region=profile.region,
        timezone=profile.timezone,
        clubs=[ClubRefOut(id=c.id, name=c.name) for c in clubs],
    )


@router.get("/partners/{partner_id}/slots")
async def get_partner_slots(
    partner_id: uuid.UUID,
    _: CurrentUser,
    session: SessionDep,
    start: date | None = None,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
    duration: Duration = 60,
) -> SlotsOut:
    _check_duration(duration)
    profile, _user = await _approved_partner(session, partner_id)
    if profile.timezone is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This partner hasn't set availability yet")
    tz = service.parse_timezone(profile.timezone)
    first = start or datetime.now(UTC).astimezone(tz).date()
    schedule = (
        await service.load_schedules(session, [profile], first, first + timedelta(days=days))
    )[partner_id]
    return _slots_out(schedule, profile.timezone, first, days, duration)
