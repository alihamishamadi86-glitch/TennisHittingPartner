"""Phone verification, notification preferences, and scheduled reminders/follow-ups.

Delivery is best-effort and at-most-once per scheduled notification: a failed channel is logged
rather than retried, so nobody gets the same reminder twice.
"""

import logging
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import phonenumbers
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_token
from app.integrations.email import EmailMessage, EmailSender
from app.integrations.sms import SmsMessage, SmsSender
from app.models import (
    Booking,
    BookingStatus,
    Club,
    NotificationKind,
    NotificationStatus,
    PhoneVerification,
    ScheduledNotification,
    User,
)
from app.services.email_templates import follow_up_email, reminder_email

logger = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 5
MAX_CODES_PER_HOUR = 5
FOLLOW_UP_DELAY = timedelta(hours=1)
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "OPTOUT"}


class NotificationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC)


# --- Phone verification -----------------------------------------------------------------


def normalize_phone(raw: str, region: str) -> str:
    try:
        number = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException as exc:
        raise NotificationError("invalid_phone", "That doesn't look like a phone number") from exc
    if not phonenumbers.is_valid_number(number):
        raise NotificationError("invalid_phone", "That doesn't look like a valid phone number")
    if phonenumbers.number_type(number) not in (
        phonenumbers.PhoneNumberType.MOBILE,
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE,
    ):
        raise NotificationError("not_mobile", "Use a mobile number that can receive texts")
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _code_hash(user_id: uuid.UUID, code: str) -> str:
    return hash_token(f"{user_id}:{code}")


async def start_phone_verification(
    session: AsyncSession, user: User, raw_phone: str, region: str, sms: SmsSender
) -> str:
    phone = normalize_phone(raw_phone, region)
    recent = await session.scalar(
        select(func.count())
        .select_from(PhoneVerification)
        .where(
            PhoneVerification.user_id == user.id,
            PhoneVerification.created_at > _now() - timedelta(hours=1),
        )
    )
    if (recent or 0) >= MAX_CODES_PER_HOUR:
        raise NotificationError("too_many_codes", "Too many codes requested. Try again later.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        PhoneVerification(
            user_id=user.id,
            phone=phone,
            code_hash=_code_hash(user.id, code),
            expires_at=_now() + CODE_TTL,
        )
    )
    await session.flush()
    await sms.send(
        SmsMessage(phone, f"Your Tennis Hitting Partner code is {code}. It expires in 10 minutes.")
    )
    return phone


async def confirm_phone(session: AsyncSession, user: User, code: str) -> User:
    pending = await session.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.user_id == user.id, PhoneVerification.verified_at.is_(None))
        .order_by(PhoneVerification.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if pending is None or pending.expires_at <= _now():
        raise NotificationError("code_expired", "That code has expired — request a new one")
    if pending.attempts >= MAX_CODE_ATTEMPTS:
        raise NotificationError("too_many_attempts", "Too many attempts — request a new code")
    pending.attempts += 1
    if not secrets.compare_digest(pending.code_hash, _code_hash(user.id, code.strip())):
        raise NotificationError("wrong_code", "That code isn't right")
    pending.verified_at = _now()
    if user.phone != pending.phone:
        user.sms_opt_in_at = None  # a new number needs a fresh opt-in
    user.phone = pending.phone
    user.phone_verified_at = _now()
    return user


def remove_phone(user: User) -> None:
    user.phone = None
    user.phone_verified_at = None
    user.sms_opt_in_at = None


def set_preferences(user: User, *, sms: bool, email: bool) -> None:
    if sms and not get_settings().sms_enabled:
        raise NotificationError("sms_disabled", "Text reminders aren't available yet")
    if sms and not (user.phone and user.phone_verified_at):
        raise NotificationError("phone_required", "Verify a mobile number to get text reminders")
    if sms and user.sms_opt_in_at is None:
        user.sms_opt_in_at = _now()  # record when consent was given
    if not sms:
        user.sms_opt_in_at = None
    user.email_reminders = email


async def opt_out_by_phone(session: AsyncSession, phone: str) -> int:
    users = (await session.scalars(select(User).where(User.phone == phone))).all()
    for user in users:
        user.sms_opt_in_at = None
    return len(users)


# --- Scheduling -------------------------------------------------------------------------


def quiet(at: datetime, timezone: str) -> bool:
    settings = get_settings()
    hour = at.astimezone(ZoneInfo(timezone)).hour
    return hour >= settings.sms_quiet_start_hour or hour < settings.sms_quiet_end_hour


def after_quiet_hours(at: datetime, timezone: str) -> datetime:
    """`at`, or the end of the quiet period it falls in (local morning)."""
    if not quiet(at, timezone):
        return at
    tz = ZoneInfo(timezone)
    local = at.astimezone(tz)
    morning = time(get_settings().sms_quiet_end_hour)
    day = local.date() if local.hour < morning.hour else local.date() + timedelta(days=1)
    return datetime.combine(day, morning, tz).astimezone(UTC)


async def schedule_for_booking(session: AsyncSession, booking: Booking) -> None:
    now = _now()
    plan = {
        NotificationKind.REMINDER_24H: booking.starts_at - timedelta(hours=24),
        NotificationKind.REMINDER_2H: booking.starts_at - timedelta(hours=2),
        NotificationKind.FOLLOW_UP: after_quiet_hours(
            booking.ends_at + FOLLOW_UP_DELAY, booking.timezone
        ),
    }
    for kind, send_at in plan.items():
        if kind is not NotificationKind.FOLLOW_UP and send_at <= now:
            continue  # booked inside the window: that reminder is moot
        await session.execute(
            pg_insert(ScheduledNotification)
            .values(
                id=uuid.uuid4(),
                booking_id=booking.id,
                kind=kind,
                send_at=send_at,
                status=NotificationStatus.PENDING,
            )
            .on_conflict_do_nothing()
        )


# --- Sending ----------------------------------------------------------------------------


def sms_allowed(user: User) -> bool:
    return bool(
        get_settings().sms_enabled and user.phone and user.phone_verified_at and user.sms_opt_in_at
    )


async def _deliver(
    recipient: User,
    email_message: EmailMessage,
    sms_text: str,
    timezone: str,
    email: EmailSender,
    sms: SmsSender,
    now: datetime,
) -> list[str]:
    channels: list[str] = []
    if recipient.email_reminders:
        try:
            await email.send(email_message)
            channels.append("email")
        except Exception:
            logger.exception("Reminder email to %s failed", recipient.id)
    if sms_allowed(recipient) and not quiet(now, timezone):
        try:
            await sms.send(SmsMessage(recipient.phone or "", sms_text))
            channels.append("sms")
        except Exception:
            logger.exception("Reminder SMS to %s failed", recipient.id)
    return channels


async def send_due(
    session: AsyncSession, email: EmailSender, sms: SmsSender, limit: int = 100
) -> int:
    """Send notifications that are due. Returns how many were processed."""
    now = _now()
    due: Sequence[ScheduledNotification] = (
        await session.scalars(
            select(ScheduledNotification)
            .where(
                ScheduledNotification.status == NotificationStatus.PENDING,
                ScheduledNotification.send_at <= now,
            )
            .order_by(ScheduledNotification.send_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    web = get_settings().public_web_url
    for item in due:
        booking = await session.get(Booking, item.booking_id)
        client = await session.get(User, booking.client_id) if booking else None
        partner = await session.get(User, booking.partner_id) if booking else None
        club = await session.get(Club, booking.club_id) if booking else None
        item.sent_at = now
        if not (booking and client and partner and club):
            item.status, item.detail = NotificationStatus.SKIPPED, "missing booking"
            continue

        if item.kind is NotificationKind.FOLLOW_UP:
            if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.COMPLETED):
                item.status, item.detail = NotificationStatus.SKIPPED, booking.status.value
                continue
            text = (
                f"Thanks for hitting with {partner.full_name}! Book again: "
                f"{web}/partners/{partner.id}"
            )
            channels = await _deliver(
                client, follow_up_email(client, partner), text, booking.timezone, email, sms, now
            )
        else:
            if booking.status is not BookingStatus.CONFIRMED or booking.starts_at <= now:
                item.status, item.detail = NotificationStatus.SKIPPED, booking.status.value
                continue
            soon = item.kind is NotificationKind.REMINDER_2H
            when = booking.starts_at.astimezone(ZoneInfo(booking.timezone)).strftime("%a %H:%M")
            channels = []
            for recipient, other in ((client, partner), (partner, client)):
                text = (
                    f"{'Starting soon' if soon else 'Reminder'}: tennis with {other.full_name} "
                    f"{when} at {club.name}. Details: {web}/sessions"
                )
                message = reminder_email(
                    recipient, other, club.name, booking.starts_at, booking.timezone, soon=soon
                )
                channels += await _deliver(
                    recipient, message, text, booking.timezone, email, sms, now
                )
        item.status = NotificationStatus.SENT
        item.detail = ",".join(channels) or "no channel"
    return len(due)
