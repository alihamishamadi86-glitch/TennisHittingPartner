import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.core.deps import ClientInfoDep, CurrentUser, SessionDep, require_roles
from app.events.outbox import commit_and_publish
from app.models import Booking, ClientProfile, Club, PartnerProfile, User, UserRole
from app.schemas.bookings import (
    BookingActionIn,
    BookingClubOut,
    BookingIn,
    BookingOut,
    CancellationTermsOut,
    PersonOut,
    WaiverOut,
    WaiverSignIn,
)
from app.services import bookings as service
from app.services import payments as payment_service
from app.services.booking_policy import (
    Action,
    Actor,
    allowed_actions,
    cancellation_outcome,
    free_cancellation_until,
)

router = APIRouter(tags=["bookings"])

ClientUser = Annotated[User, Depends(require_roles(UserRole.CLIENT))]
AdminUser = Annotated[User, Depends(require_roles(UserRole.ADMIN))]

ERROR_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND,
    "slot_taken": status.HTTP_409_CONFLICT,
    "client_overlap": status.HTTP_409_CONFLICT,
    "slot_unavailable": status.HTTP_409_CONFLICT,
    "waiver_required": status.HTTP_409_CONFLICT,
    "email_unverified": status.HTTP_409_CONFLICT,
    "profile_incomplete": status.HTTP_409_CONFLICT,
    "not_allowed": status.HTTP_409_CONFLICT,
    "payment_required": status.HTTP_409_CONFLICT,
}


def _http_error(exc: service.BookingError) -> HTTPException:
    return HTTPException(
        ERROR_STATUS.get(exc.code, status.HTTP_422_UNPROCESSABLE_CONTENT),
        {"code": exc.code, "message": exc.message},
    )


async def booking_out(session: SessionDep, booking: Booking, viewer: User) -> BookingOut:
    client = await session.get(User, booking.client_id)
    partner = await session.get(User, booking.partner_id)
    partner_profile = await session.get(PartnerProfile, booking.partner_id)
    client_profile = await session.get(ClientProfile, booking.client_id)
    club = await session.get(Club, booking.club_id)
    assert client and partner and club
    now = datetime.now(UTC)
    actor = service.actor_for(viewer, booking) or Actor.CLIENT
    actions = allowed_actions(
        status=booking.status,
        actor=actor,
        starts_at=booking.starts_at,
        hold_expires_at=booking.hold_expires_at,
        now=now,
    )
    terms = None
    if Action.CANCEL in actions:
        outcome = cancellation_outcome(
            status=booking.status,
            actor=actor,
            starts_at=booking.starts_at,
            now=now,
            policy=service.policy(),
        )
        terms = CancellationTermsOut(
            free_until=free_cancellation_until(booking.starts_at, service.policy()),
            fee_fraction_if_cancelled_now=outcome.fee_fraction,
        )
    paid = await payment_service.succeeded_payment(session, booking.id)
    return BookingOut(
        id=booking.id,
        currency=booking.currency,
        price_cents=booking.price_cents,
        paid_cents=(paid.amount_cents + paid.credit_applied_cents) if paid else 0,
        refunded_cents=await payment_service.refunded_cents(session, booking.id),
        status=booking.status,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        duration_minutes=booking.duration_minutes,
        timezone=booking.timezone,
        club=BookingClubOut(
            id=club.id, name=club.name, address=club.address, lat=club.lat, lon=club.lon
        ),
        client=PersonOut(
            id=client.id,
            full_name=client.full_name,
            avatar_url=client.avatar_url,
            ntrp_rating=client_profile.ntrp_rating if client_profile else None,
        ),
        partner=PersonOut(
            id=partner.id,
            full_name=partner.full_name,
            avatar_url=partner.avatar_url,
            ntrp_rating=partner_profile.verified_ntrp_rating if partner_profile else None,
        ),
        hold_expires_at=booking.hold_expires_at,
        confirmed_at=booking.confirmed_at,
        note=booking.client_note,
        cancelled_at=booking.cancelled_at,
        cancellation_reason=booking.cancellation_reason,
        cancellation_fee_fraction=booking.cancellation_fee_fraction,
        credit_issued=booking.credit_issued,
        actions=sorted(actions),
        cancellation_terms=terms,
    )


async def _load(session: SessionDep, booking_id: uuid.UUID, user: User) -> Booking:
    booking = await session.get(Booking, booking_id, with_for_update=True)
    if booking is None or service.actor_for(user, booking) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    return booking


# --- Waiver -----------------------------------------------------------------------------


@router.get("/waiver", responses={404: {"description": "No active waiver"}})
async def get_waiver(user: CurrentUser, session: SessionDep) -> WaiverOut:
    waiver = await service.current_waiver(session)
    if waiver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No waiver")
    return WaiverOut(
        version=waiver.version,
        title=waiver.title,
        body=waiver.body,
        signed=await service.has_signed_current_waiver(session, user.id),
    )


@router.post("/waiver/sign")
async def sign_waiver(
    body: WaiverSignIn, user: CurrentUser, session: SessionDep, client: ClientInfoDep
) -> WaiverOut:
    try:
        await service.sign_waiver(session, user, body.full_name, client)
    except service.BookingError as exc:
        raise _http_error(exc) from exc
    await session.commit()
    return await get_waiver(user, session)


# --- Bookings ---------------------------------------------------------------------------


@router.post("/bookings", status_code=status.HTTP_201_CREATED)
async def create_booking(body: BookingIn, user: ClientUser, session: SessionDep) -> BookingOut:
    """Hold a slot for the client, to be paid for before `hold_expires_at`. With payments
    switched off the booking is confirmed straight away."""
    try:
        booking = await service.create_hold(
            session,
            client=user,
            partner_id=body.partner_id,
            club_id=body.club_id,
            starts_at=body.starts_at,
            duration_minutes=body.duration_minutes,
            note=body.note,
        )
    except service.BookingError as exc:
        await session.commit()  # keep any holds we expired on the way
        raise _http_error(exc) from exc
    await commit_and_publish(session)
    return await booking_out(session, booking, user)


@router.get("/bookings")
async def list_bookings(
    user: CurrentUser,
    session: SessionDep,
    scope: Annotated[str, Query(pattern="^(upcoming|past)$")] = "upcoming",
) -> list[BookingOut]:
    rows = await service.list_for_user(session, user, upcoming=scope == "upcoming")
    return [await booking_out(session, b, user) for b in rows]


@router.get("/bookings/{booking_id}")
async def get_booking(booking_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BookingOut:
    booking = await session.get(Booking, booking_id)
    if booking is None or service.actor_for(user, booking) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking not found")
    return await booking_out(session, booking, user)


async def _act(
    booking_id: uuid.UUID,
    user: User,
    session: SessionDep,
    action: Action,
    reason: str = "",
) -> BookingOut:
    booking = await _load(session, booking_id, user)
    try:
        await service.apply_action(session, booking, user, action, reason=reason)
    except service.BookingError as exc:
        raise _http_error(exc) from exc
    await commit_and_publish(session)
    return await booking_out(session, booking, user)


@router.post("/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: uuid.UUID, body: BookingActionIn, user: CurrentUser, session: SessionDep
) -> BookingOut:
    return await _act(booking_id, user, session, Action.CANCEL, body.reason)


@router.post("/bookings/{booking_id}/complete")
async def complete_booking(
    booking_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> BookingOut:
    return await _act(booking_id, user, session, Action.COMPLETE)


@router.post("/bookings/{booking_id}/no-show")
async def mark_no_show(booking_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BookingOut:
    return await _act(booking_id, user, session, Action.NO_SHOW)


@router.post("/admin/bookings/{booking_id}/rainout")
async def rain_out(
    booking_id: uuid.UUID, body: BookingActionIn, user: AdminUser, session: SessionDep
) -> BookingOut:
    return await _act(booking_id, user, session, Action.RAIN_OUT, body.reason)


@router.get("/admin/bookings")
async def admin_list_bookings(
    admin: AdminUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[BookingOut]:
    rows = (
        await session.scalars(select(Booking).order_by(Booking.starts_at.desc()).limit(limit))
    ).all()
    return [await booking_out(session, b, admin) for b in rows]
