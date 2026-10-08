"""Partner availability (weekly rules + date exceptions) and partner search."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID
from geoalchemy2.types import Geography
from sqlalchemy import ColumnElement, and_, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingStatus,
    Club,
    ExceptionKind,
    PartnerProfile,
    PartnerStatus,
    User,
    UserClub,
)
from app.services.slots import DateException, WeeklyWindow, generate_slots

MAX_RULES = 40
MAX_EXCEPTIONS_AHEAD = 100


class AvailabilityError(Exception):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AvailabilityError(f"Unknown timezone: {name}") from exc


# --- Editing ----------------------------------------------------------------------------


async def list_rules(session: AsyncSession, partner_id: uuid.UUID) -> list[AvailabilityRule]:
    return list(
        await session.scalars(
            select(AvailabilityRule)
            .where(AvailabilityRule.partner_id == partner_id)
            .order_by(AvailabilityRule.weekday, AvailabilityRule.start_minute)
        )
    )


async def list_upcoming_exceptions(
    session: AsyncSession, partner_id: uuid.UUID, today: date
) -> list[AvailabilityException]:
    return list(
        await session.scalars(
            select(AvailabilityException)
            .where(
                AvailabilityException.partner_id == partner_id,
                AvailabilityException.date >= today,
            )
            .order_by(AvailabilityException.date, AvailabilityException.start_minute)
        )
    )


async def replace_weekly_schedule(
    session: AsyncSession,
    profile: PartnerProfile,
    timezone: str,
    windows: Sequence[tuple[int, int, int]],
) -> list[AvailabilityRule]:
    """Replace the weekly rules. `windows` are (weekday, start_minute, end_minute)."""
    parse_timezone(timezone)
    if len(windows) > MAX_RULES:
        raise AvailabilityError(f"At most {MAX_RULES} weekly windows")
    by_day: dict[int, list[tuple[int, int]]] = {}
    for weekday, start, end in windows:
        by_day.setdefault(weekday, []).append((start, end))
    for spans in by_day.values():
        spans.sort()
        for (_, prev_end), (next_start, _) in pairwise(spans):
            if next_start < prev_end:
                raise AvailabilityError("Time windows on the same day overlap")

    profile.timezone = timezone
    await session.execute(
        delete(AvailabilityRule).where(AvailabilityRule.partner_id == profile.user_id)
    )
    for weekday, start, end in windows:
        session.add(
            AvailabilityRule(
                partner_id=profile.user_id, weekday=weekday, start_minute=start, end_minute=end
            )
        )
    await session.flush()
    return await list_rules(session, profile.user_id)


async def add_exception(
    session: AsyncSession,
    profile: PartnerProfile,
    *,
    day: date,
    kind: ExceptionKind,
    start: int | None,
    end: int | None,
    note: str,
) -> AvailabilityException:
    tz = parse_timezone(profile.timezone or "UTC")
    today = _now().astimezone(tz).date()
    if day < today:
        raise AvailabilityError("That date has passed")
    if (start is None) != (end is None):
        raise AvailabilityError("Give both a start and an end time, or neither")
    if kind is ExceptionKind.AVAILABLE and start is None:
        raise AvailabilityError("Extra hours need a start and end time")
    upcoming = await session.scalar(
        select(func.count())
        .select_from(AvailabilityException)
        .where(
            AvailabilityException.partner_id == profile.user_id,
            AvailabilityException.date >= today,
        )
    )
    if (upcoming or 0) >= MAX_EXCEPTIONS_AHEAD:
        raise AvailabilityError("Too many upcoming exceptions")
    exception = AvailabilityException(
        partner_id=profile.user_id,
        date=day,
        kind=kind,
        start_minute=start,
        end_minute=end,
        note=note.strip(),
    )
    session.add(exception)
    await session.flush()
    return exception


async def delete_exception(
    session: AsyncSession, partner_id: uuid.UUID, exception_id: uuid.UUID
) -> bool:
    deleted = await session.scalar(
        delete(AvailabilityException)
        .where(
            AvailabilityException.id == exception_id,
            AvailabilityException.partner_id == partner_id,
        )
        .returning(AvailabilityException.id)
    )
    return deleted is not None


# --- Slots ------------------------------------------------------------------------------


@dataclass
class PartnerSchedule:
    tz: ZoneInfo
    weekly: list[WeeklyWindow] = field(default_factory=list)
    exceptions: list[DateException] = field(default_factory=list)
    # Existing bookings, widened by the travel buffer on both sides.
    busy: list[tuple[datetime, datetime]] = field(default_factory=list)


async def load_schedules(
    session: AsyncSession, partners: Sequence[PartnerProfile], first_day: date, last_day: date
) -> dict[uuid.UUID, PartnerSchedule]:
    """Weekly rules, exceptions and existing bookings for many partners in three queries."""
    schedules = {
        p.user_id: PartnerSchedule(tz=parse_timezone(p.timezone)) for p in partners if p.timezone
    }
    if not schedules:
        return {}
    ids = list(schedules)
    for rule in await session.scalars(
        select(AvailabilityRule).where(AvailabilityRule.partner_id.in_(ids))
    ):
        schedules[rule.partner_id].weekly.append(
            WeeklyWindow(rule.weekday, rule.start_minute, rule.end_minute)
        )
    for exc in await session.scalars(
        select(AvailabilityException).where(
            AvailabilityException.partner_id.in_(ids),
            AvailabilityException.date.between(first_day, last_day),
        )
    ):
        schedules[exc.partner_id].exceptions.append(
            DateException(
                exc.date, exc.kind is ExceptionKind.AVAILABLE, exc.start_minute, exc.end_minute
            )
        )
    now = _now()
    buffer = timedelta(minutes=get_settings().travel_buffer_minutes)
    range_start = datetime.combine(first_day, datetime.min.time(), UTC) - timedelta(days=1)
    range_end = datetime.combine(last_day, datetime.min.time(), UTC) + timedelta(days=2)
    for booking in await session.scalars(
        select(Booking).where(
            Booking.partner_id.in_(ids),
            Booking.starts_at < range_end,
            Booking.blocked_until > range_start,
            or_(
                Booking.status == BookingStatus.CONFIRMED,
                and_(Booking.status == BookingStatus.HELD, Booking.hold_expires_at > now),
            ),
        )
    ):
        schedules[booking.partner_id].busy.append(
            (booking.starts_at - buffer, booking.blocked_until)
        )
    return schedules


def slots_for(
    schedule: PartnerSchedule,
    first_day: date,
    last_day: date,
    duration_minutes: int,
    now: datetime,
) -> list[datetime]:
    settings = get_settings()
    horizon = now.astimezone(schedule.tz).date() + timedelta(days=settings.booking_horizon_days)
    if first_day > horizon:
        return []
    return generate_slots(
        weekly=schedule.weekly,
        exceptions=schedule.exceptions,
        tz=schedule.tz,
        first_day=first_day,
        last_day=min(last_day, horizon),
        duration=timedelta(minutes=duration_minutes),
        now=now,
        min_notice=timedelta(hours=settings.min_booking_notice_hours),
        step=timedelta(minutes=settings.slot_step_minutes),
        busy=schedule.busy,
    )


# --- Search -----------------------------------------------------------------------------


@dataclass
class NearbyClub:
    id: uuid.UUID
    name: str
    distance_m: float
    # For suggestions: the player's own court this club is at (distance 0) or near.
    near_court: str | None = None


@dataclass
class PartnerMatch:
    profile: PartnerProfile
    user: User
    clubs: list[NearbyClub]
    slots: list[datetime]
    next_slot: datetime | None

    @property
    def distance_m(self) -> float:
        return min(c.distance_m for c in self.clubs)


def _point(lat: float, lon: float) -> ColumnElement[Geography]:
    return cast(ST_SetSRID(ST_MakePoint(lon, lat), 4326), Geography)


async def search_partners(
    session: AsyncSession,
    *,
    lat: float,
    lon: float,
    radius_km: float,
    day: date | None,
    duration_minutes: int,
    min_level: Decimal | None,
    club_id: uuid.UUID | None = None,
    limit: int = 50,
    now: datetime | None = None,
) -> list[PartnerMatch]:
    """Approved partners who play at a club near the point, best matches first:
    open slots on `day` (or soonest availability), then distance, then level."""
    now = now or _now()
    point = _point(lat, lon)
    distance = ST_Distance(Club.location, point)
    query = (
        select(PartnerProfile, User, Club.id, Club.name, distance)
        .join(User, User.id == PartnerProfile.user_id)
        .join(UserClub, UserClub.user_id == PartnerProfile.user_id)
        .join(Club, Club.id == UserClub.club_id)
        .where(
            PartnerProfile.status == PartnerStatus.APPROVED,
            PartnerProfile.timezone.is_not(None),
            User.is_active.is_(True),
            Club.active.is_(True),
            ST_DWithin(Club.location, point, radius_km * 1000),
        )
        .order_by(distance)
    )
    if club_id is not None:
        query = query.where(Club.id == club_id)
    if min_level is not None:
        query = query.where(PartnerProfile.verified_ntrp_rating >= min_level)

    found: dict[uuid.UUID, tuple[PartnerProfile, User, list[NearbyClub]]] = {}
    for profile, user, c_id, c_name, dist in (await session.execute(query)).all():
        entry = found.setdefault(profile.user_id, (profile, user, []))
        entry[2].append(NearbyClub(c_id, c_name, float(dist)))
    return await _with_slots(session, found, day, duration_minutes, now, limit)


async def suggest_partners(
    session: AsyncSession,
    *,
    player_id: uuid.UUID,
    radius_km: float,
    day: date | None,
    duration_minutes: int,
    min_level: Decimal | None,
    limit: int = 50,
    now: datetime | None = None,
) -> list[PartnerMatch]:
    """Approved partners who play at the player's courts (or within `radius_km` of one),
    ranked like search: bookable first, then same court before nearby, then level."""
    now = now or _now()
    mine, theirs = aliased(Club), aliased(Club)
    my_link, their_link = aliased(UserClub), aliased(UserClub)
    distance = ST_Distance(theirs.location, mine.location)
    query = (
        select(PartnerProfile, User, theirs.id, theirs.name, mine.name, distance)
        .join(User, User.id == PartnerProfile.user_id)
        .join(their_link, their_link.user_id == PartnerProfile.user_id)
        .join(theirs, theirs.id == their_link.club_id)
        .join(mine, ST_DWithin(theirs.location, mine.location, radius_km * 1000))
        .join(my_link, and_(my_link.club_id == mine.id, my_link.user_id == player_id))
        .where(
            PartnerProfile.status == PartnerStatus.APPROVED,
            PartnerProfile.timezone.is_not(None),
            PartnerProfile.user_id != player_id,
            User.is_active.is_(True),
            theirs.active.is_(True),
        )
        .order_by(distance, mine.name)
    )
    if min_level is not None:
        query = query.where(PartnerProfile.verified_ntrp_rating >= min_level)

    found: dict[uuid.UUID, tuple[PartnerProfile, User, list[NearbyClub]]] = {}
    for profile, user, c_id, c_name, near, dist in (await session.execute(query)).all():
        clubs = found.setdefault(profile.user_id, (profile, user, []))[2]
        if all(c.id != c_id for c in clubs):  # nearest of the player's courts wins
            clubs.append(NearbyClub(c_id, c_name, float(dist), near_court=near))
    return await _with_slots(session, found, day, duration_minutes, now, limit)


async def _with_slots(
    session: AsyncSession,
    found: dict[uuid.UUID, tuple[PartnerProfile, User, list[NearbyClub]]],
    day: date | None,
    duration_minutes: int,
    now: datetime,
    limit: int,
) -> list[PartnerMatch]:
    """Attach open slots to candidate partners (clubs nearest first) and rank them:
    open slots on `day` (or soonest availability), then distance, then level."""
    if not found:
        return []
    profiles = [entry[0] for entry in found.values()]
    today = min(now.astimezone(parse_timezone(p.timezone or "UTC")).date() for p in profiles)
    window_end = today + timedelta(days=14)
    first, last = (day, day) if day else (today, window_end)
    schedules = await load_schedules(session, profiles, min(first, today), max(last, window_end))

    matches = []
    for profile, user, clubs in found.values():
        schedule = schedules.get(profile.user_id)
        if schedule is None:
            continue
        upcoming = slots_for(schedule, today, window_end, duration_minutes, now)
        on_day = slots_for(schedule, day, day, duration_minutes, now) if day else []
        matches.append(
            PartnerMatch(
                profile=profile,
                user=user,
                clubs=clubs[:3],
                slots=on_day,
                next_slot=upcoming[0] if upcoming else None,
            )
        )

    def rank(m: PartnerMatch) -> tuple[bool, float, Decimal]:
        bookable = bool(m.slots) if day else m.next_slot is not None
        return (not bookable, m.distance_m, -(m.profile.verified_ntrp_rating or Decimal(0)))

    matches.sort(key=rank)
    return matches[:limit]


async def partner_clubs(session: AsyncSession, partner_id: uuid.UUID) -> list[Club]:
    return list(
        await session.scalars(
            select(Club)
            .join(UserClub, UserClub.club_id == Club.id)
            .where(UserClub.user_id == partner_id, Club.active.is_(True))
            .order_by(Club.name)
        )
    )
