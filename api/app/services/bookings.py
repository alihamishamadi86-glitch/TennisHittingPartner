"""Bookings: waiver, holds, confirmation, cancellation and session outcomes.

Double-booking is prevented by the database (exclusion constraints), not by checks here:
the slot validation below gives friendly errors, and the constraint is the final arbiter
when two clients race for the same time.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import (
    BOOKING_CANCELLED,
    BOOKING_COMPLETED,
    BOOKING_CONFIRMED,
    BOOKING_RAINED_OUT,
)
from app.events.outbox import record_event
from app.models import (
    ACTIVE_STATUSES,
    Booking,
    BookingStatus,
    ClientProfile,
    Club,
    PartnerProfile,
    PartnerStatus,
    User,
    UserClub,
    UserRole,
    WaiverSignature,
    WaiverVersion,
)
from app.services import availability, payments
from app.services.auth import ClientInfo
from app.services.booking_policy import (
    Action,
    Actor,
    Policy,
    PolicyError,
    allowed_actions,
    cancellation_outcome,
    transition,
)

PARTNER_OVERLAP_CONSTRAINT = "ex_bookings_partner_time"
CLIENT_OVERLAP_CONSTRAINT = "ex_bookings_client_time"


class BookingError(Exception):
    """User-facing booking failure with a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


def policy() -> Policy:
    settings = get_settings()
    return Policy(
        free_cancellation=timedelta(hours=settings.free_cancellation_hours),
        late_fee_fraction=Decimal(str(settings.late_cancellation_fee_fraction)),
    )


# --- Waiver -----------------------------------------------------------------------------


async def current_waiver(session: AsyncSession) -> WaiverVersion | None:
    return await session.scalar(
        select(WaiverVersion)
        .where(WaiverVersion.active.is_(True))
        .order_by(WaiverVersion.version.desc())
        .limit(1)
    )


async def has_signed_current_waiver(session: AsyncSession, user_id: uuid.UUID) -> bool:
    waiver = await current_waiver(session)
    if waiver is None:
        return True  # nothing to sign
    signed = await session.scalar(
        select(WaiverSignature.id).where(
            WaiverSignature.user_id == user_id, WaiverSignature.waiver_version_id == waiver.id
        )
    )
    return signed is not None


async def sign_waiver(
    session: AsyncSession, user: User, signed_name: str, client: ClientInfo
) -> WaiverSignature:
    waiver = await current_waiver(session)
    if waiver is None:
        raise BookingError("no_waiver", "There is no waiver to sign")
    if " ".join(signed_name.split()).lower() != " ".join(user.full_name.split()).lower():
        raise BookingError("name_mismatch", "Type your full name exactly as on your account")
    existing = await session.scalar(
        select(WaiverSignature).where(
            WaiverSignature.user_id == user.id, WaiverSignature.waiver_version_id == waiver.id
        )
    )
    if existing is not None:
        return existing
    signature = WaiverSignature(
        user_id=user.id,
        waiver_version_id=waiver.id,
        signed_name=signed_name.strip(),
        ip_address=client.ip_address,
        user_agent=(client.user_agent or "")[:512] or None,
    )
    session.add(signature)
    await session.flush()
    return signature


# --- Holds ------------------------------------------------------------------------------


async def expire_stale_holds(
    session: AsyncSession,
    now: datetime,
    *,
    partner_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
) -> int:
    """Mark lapsed holds expired so they stop blocking the slot. Runs before every booking
    attempt (for the parties involved) and periodically for everyone."""
    stmt = update(Booking).where(
        Booking.status == BookingStatus.HELD, Booking.hold_expires_at <= now
    )
    if partner_id is not None or client_id is not None:
        stmt = stmt.where(or_(Booking.partner_id == partner_id, Booking.client_id == client_id))
    result = await session.execute(stmt.values(status=BookingStatus.EXPIRED).returning(Booking.id))
    return len(result.all())


def _constraint_name(exc: IntegrityError) -> str | None:
    error: Any = exc.orig
    while error is not None:
        name = getattr(error, "constraint_name", None)
        if name:
            return str(name)
        error = error.__cause__
    return None


# --- Creating ---------------------------------------------------------------------------


async def create_hold(
    session: AsyncSession,
    *,
    client: User,
    partner_id: uuid.UUID,
    club_id: uuid.UUID,
    starts_at: datetime,
    duration_minutes: int,
    note: str,
    now: datetime | None = None,
) -> Booking:
    now = now or _now()
    settings = get_settings()

    if not client.is_email_verified:
        raise BookingError("email_unverified", "Confirm your email address before booking")
    if await session.get(ClientProfile, client.id) is None:
        raise BookingError("profile_incomplete", "Complete your player profile before booking")
    if not await has_signed_current_waiver(session, client.id):
        raise BookingError("waiver_required", "Please read and sign the waiver first")
    if duration_minutes not in settings.session_durations_minutes:
        raise BookingError("invalid_duration", "Choose a 60 or 90 minute session")

    profile = await session.get(PartnerProfile, partner_id)
    if profile is None or profile.status is not PartnerStatus.APPROVED or not profile.timezone:
        raise BookingError("partner_unavailable", "This partner isn't taking bookings")
    partner_club = await session.scalar(
        select(Club)
        .join(UserClub, UserClub.club_id == Club.id)
        .where(UserClub.user_id == partner_id, Club.id == club_id, Club.active.is_(True))
    )
    if partner_club is None:
        raise BookingError("invalid_club", "This partner doesn't play at that club")

    await expire_stale_holds(session, now, partner_id=partner_id, client_id=client.id)

    starts_at = starts_at.astimezone(UTC)
    schedule = (
        await availability.load_schedules(
            session,
            [profile],
            (starts_at - timedelta(days=1)).date(),
            (starts_at + timedelta(days=1)).date(),
        )
    )[partner_id]
    day = starts_at.astimezone(schedule.tz).date()
    if starts_at not in availability.slots_for(schedule, day, day, duration_minutes, now):
        raise BookingError("slot_unavailable", "That time isn't available — please pick another")

    ends_at = starts_at + timedelta(minutes=duration_minutes)
    price_cents, partner_pay_cents = payments.pricing_for(duration_minutes)
    booking = Booking(
        client_id=client.id,
        partner_id=partner_id,
        club_id=club_id,
        starts_at=starts_at,
        ends_at=ends_at,
        blocked_until=ends_at + timedelta(minutes=settings.travel_buffer_minutes),
        duration_minutes=duration_minutes,
        timezone=profile.timezone,
        status=BookingStatus.HELD,
        hold_expires_at=now + timedelta(minutes=settings.hold_minutes),
        client_note=note.strip(),
        currency=settings.currency,
        price_cents=price_cents,
        partner_pay_cents=partner_pay_cents,
    )
    try:
        async with session.begin_nested():
            session.add(booking)
    except IntegrityError as exc:
        constraint = _constraint_name(exc)
        if constraint == PARTNER_OVERLAP_CONSTRAINT:
            raise BookingError("slot_taken", "Someone just booked that time") from exc
        if constraint == CLIENT_OVERLAP_CONSTRAINT:
            raise BookingError("client_overlap", "You already have a session at that time") from exc
        raise
    return booking


# --- Changing ---------------------------------------------------------------------------


def actor_for(user: User, booking: Booking) -> Actor | None:
    if user.role is UserRole.ADMIN:
        return Actor.ADMIN
    if user.id == booking.client_id:
        return Actor.CLIENT
    if user.id == booking.partner_id:
        return Actor.PARTNER
    return None


def _event(booking: Booking, **extra: Any) -> dict[str, Any]:
    return {"booking_id": str(booking.id), **extra}


async def apply_action(
    session: AsyncSession,
    booking: Booking,
    user: User,
    action: Action,
    *,
    reason: str = "",
    now: datetime | None = None,
) -> Booking:
    now = now or _now()
    actor = actor_for(user, booking)
    if actor is None:
        raise BookingError("not_found", "Booking not found")

    if action is Action.CONFIRM:
        # Bookings are confirmed by payment (webhook), never directly.
        raise BookingError("payment_required", "Pay to confirm this booking")

    if action is Action.CANCEL:
        if Action.CANCEL not in allowed_actions(
            status=booking.status,
            actor=actor,
            starts_at=booking.starts_at,
            hold_expires_at=booking.hold_expires_at,
            now=now,
        ):
            raise BookingError("not_allowed", "This booking can't be cancelled now")
        try:
            outcome = cancellation_outcome(
                status=booking.status,
                actor=actor,
                starts_at=booking.starts_at,
                now=now,
                policy=policy(),
            )
        except PolicyError as exc:
            raise BookingError("not_allowed", str(exc)) from exc
        was_confirmed = booking.status is BookingStatus.CONFIRMED
        booking.status = outcome.status
        booking.cancellation_fee_fraction = outcome.fee_fraction
        booking.cancelled_at = now
        booking.cancelled_by_id = user.id
        booking.cancellation_reason = reason.strip()
        if was_confirmed:
            await payments.refund_after_cancellation(session, booking, outcome.fee_fraction)
            record_event(session, BOOKING_CANCELLED, _event(booking, by=actor.value))
        return booking

    try:
        target = transition(
            status=booking.status,
            action=action,
            actor=actor,
            starts_at=booking.starts_at,
            hold_expires_at=booking.hold_expires_at,
            now=now,
        )
    except PolicyError as exc:
        raise BookingError("not_allowed", str(exc)) from exc
    booking.status = target
    if target is BookingStatus.CONFIRMED:
        booking.confirmed_at = now
        booking.hold_expires_at = None
        record_event(session, BOOKING_CONFIRMED, _event(booking))
    elif target is BookingStatus.COMPLETED:
        record_event(session, BOOKING_COMPLETED, _event(booking))
    elif target is BookingStatus.RAINED_OUT:
        booking.credit_issued = await payments.credit_rain_out(session, booking) > 0
        booking.cancelled_at = now
        booking.cancelled_by_id = user.id
        booking.cancellation_reason = reason.strip() or "Rained out"
        booking.cancellation_fee_fraction = Decimal(0)
        record_event(session, BOOKING_RAINED_OUT, _event(booking))
    return booking


# --- Queries ----------------------------------------------------------------------------


async def list_for_user(
    session: AsyncSession, user: User, *, upcoming: bool, now: datetime | None = None
) -> Sequence[Booking]:
    now = now or _now()
    owner = Booking.partner_id if user.role is UserRole.PARTNER else Booking.client_id
    live = or_(
        Booking.status == BookingStatus.CONFIRMED,
        and_(Booking.status == BookingStatus.HELD, Booking.hold_expires_at > now),
    )
    query = select(Booking).where(owner == user.id)
    if upcoming:
        query = query.where(live, Booking.ends_at > now).order_by(Booking.starts_at)
    else:
        query = (
            query.where(
                or_(Booking.ends_at <= now, Booking.status.not_in(ACTIVE_STATUSES)),
                # Abandoned checkouts aren't history worth showing.
                Booking.status != BookingStatus.EXPIRED,
            )
            .order_by(Booking.starts_at.desc())
            .limit(100)
        )
    return (await session.scalars(query)).all()
