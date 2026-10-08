import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.events.catalog import BOOKING_CANCELLED, BOOKING_CONFIRMED, BOOKING_RAINED_OUT
from app.events.envelope import EventEnvelope
from app.events.registry import handles
from app.integrations.email import get_email_sender
from app.integrations.sms import SmsMessage, get_sms_sender
from app.models import Booking, Club, User
from app.services.email_templates import (
    booking_cancelled_email,
    booking_confirmed_email,
    booking_rained_out_email,
)
from app.services.notifications import quiet, schedule_for_booking, sms_allowed


async def _load(
    session: AsyncSession, envelope: EventEnvelope
) -> tuple[Booking, User, User, Club] | None:
    booking = await session.get(Booking, uuid.UUID(envelope.data["booking_id"]))
    if booking is None:
        return None
    client = await session.get(User, booking.client_id)
    partner = await session.get(User, booking.partner_id)
    club = await session.get(Club, booking.club_id)
    if client is None or partner is None or club is None:
        return None
    return booking, client, partner, club


@handles(BOOKING_CONFIRMED, consumer="bookings.email_confirmation")
async def email_confirmation(session: AsyncSession, envelope: EventEnvelope) -> None:
    loaded = await _load(session, envelope)
    if loaded is None:
        return
    booking, client, partner, club = loaded
    sender = get_email_sender()
    args = (club.name, booking.starts_at, booking.timezone, booking.duration_minutes)
    await sender.send(booking_confirmed_email(client, partner, *args, to_partner=False))
    await sender.send(booking_confirmed_email(partner, client, *args, to_partner=True))

    # Text the partner (not at night): a new session in their diary.
    if sms_allowed(partner) and not quiet(datetime.now(UTC), booking.timezone):
        when = booking.starts_at.astimezone(ZoneInfo(booking.timezone)).strftime("%a %d %b %H:%M")
        await get_sms_sender().send(
            SmsMessage(
                partner.phone or "",
                f"New session: {client.full_name}, {when} at {club.name}. "
                f"{get_settings().public_web_url}/sessions",
            )
        )


@handles(BOOKING_CONFIRMED, consumer="bookings.schedule_notifications")
async def schedule_notifications(session: AsyncSession, envelope: EventEnvelope) -> None:
    booking = await session.get(Booking, uuid.UUID(envelope.data["booking_id"]))
    if booking is not None:
        await schedule_for_booking(session, booking)


@handles(BOOKING_CANCELLED, consumer="bookings.email_cancellation")
async def email_cancellation(session: AsyncSession, envelope: EventEnvelope) -> None:
    loaded = await _load(session, envelope)
    if loaded is None:
        return
    booking, client, partner, club = loaded
    by = envelope.data.get("by", "client")
    # Tell the other party; admins cancelling notify both.
    recipients = {"client": [partner], "partner": [client]}.get(by, [client, partner])
    sender = get_email_sender()
    for recipient in recipients:
        await sender.send(
            booking_cancelled_email(
                recipient,
                by,
                club.name,
                booking.starts_at,
                booking.timezone,
                booking.duration_minutes,
                booking.cancellation_reason,
            )
        )


@handles(BOOKING_RAINED_OUT, consumer="bookings.email_rain_out")
async def email_rain_out(session: AsyncSession, envelope: EventEnvelope) -> None:
    loaded = await _load(session, envelope)
    if loaded is None:
        return
    booking, client, _partner, club = loaded
    await get_email_sender().send(
        booking_rained_out_email(
            client, club.name, booking.starts_at, booking.timezone, booking.duration_minutes
        )
    )
