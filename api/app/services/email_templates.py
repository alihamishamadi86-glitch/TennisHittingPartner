from datetime import datetime
from html import escape
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.integrations.email import EmailMessage
from app.models import User


def _link(path: str, token: str) -> str:
    return f"{get_settings().public_web_url}{path}?{urlencode({'token': token})}"


def _html(greeting: str, body: str, cta: str, link: str, footer: str) -> str:
    return f"""<!doctype html>
<html><body style="font-family:system-ui,sans-serif;color:#18181b;max-width:560px;margin:0 auto;padding:24px">
<p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#059669;font-weight:600">Tennis Hitting Partner</p>
<p>{escape(greeting)}</p>
<p>{escape(body)}</p>
<p style="margin:28px 0"><a href="{escape(link)}" style="background:#059669;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">{escape(cta)}</a></p>
<p style="font-size:13px;color:#71717a">{escape(footer)}</p>
</body></html>"""


def verification_email(user: User, token: str) -> EmailMessage:
    link = _link("/verify-email", token)
    hours = get_settings().email_verification_ttl_hours
    greeting = f"Hi {user.full_name or 'there'},"
    body = "Confirm your email address to finish setting up your account."
    footer = f"This link expires in {hours} hours. If you didn't sign up, ignore this email."
    return EmailMessage(
        to=user.email,
        subject="Confirm your email",
        text=f"{greeting}\n\n{body}\n\n{link}\n\n{footer}\n",
        html=_html(greeting, body, "Confirm email", link, footer),
    )


def password_reset_email(user: User, token: str) -> EmailMessage:
    link = _link("/reset-password", token)
    minutes = get_settings().password_reset_ttl_minutes
    greeting = f"Hi {user.full_name or 'there'},"
    body = "We received a request to reset your password."
    footer = (
        f"This link expires in {minutes} minutes. If you didn't ask for this, you can ignore "
        "this email — your password won't change."
    )
    return EmailMessage(
        to=user.email,
        subject="Reset your password",
        text=f"{greeting}\n\n{body}\n\n{link}\n\n{footer}\n",
        html=_html(greeting, body, "Reset password", link, footer),
    )


def partner_application_admin_email(admin: User, partner: User) -> EmailMessage:
    link = f"{get_settings().public_web_url}/admin/partners/{partner.id}"
    greeting = f"Hi {admin.full_name or 'there'},"
    body = f"{partner.full_name or partner.email} applied to become a hitting partner."
    footer = "Review their profile and schedule a court screening."
    return EmailMessage(
        to=admin.email,
        subject=f"New partner application: {partner.full_name or partner.email}",
        text=f"{greeting}\n\n{body}\n\n{link}\n\n{footer}\n",
        html=_html(greeting, body, "Review application", link, footer),
    )


PARTNER_DECISION_COPY = {
    "screened": (
        "You passed your court screening",
        "Great hitting with you! You've passed the screening — final approval is on its way.",
    ),
    "approved": (
        "You're approved as a hitting partner",
        "Welcome aboard! Your profile is approved. Next, set the clubs and times you can play.",
    ),
    "rejected": (
        "Update on your partner application",
        "Thanks for applying. We can't approve your application right now.",
    ),
}


def partner_decision_email(partner: User, status: str, note: str) -> EmailMessage:
    subject, body = PARTNER_DECISION_COPY[status]
    link = f"{get_settings().public_web_url}/dashboard"
    greeting = f"Hi {partner.full_name or 'there'},"
    footer = f"Note from our team: {note}" if note else "Questions? Just reply to this email."
    return EmailMessage(
        to=partner.email,
        subject=subject,
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "Open dashboard", link, footer),
    )


def _when(starts_at: datetime, timezone: str, duration: int) -> str:
    local = starts_at.astimezone(ZoneInfo(timezone))
    return f"{local:%A %d %B, %H:%M} ({local.tzname()}), {duration} minutes"


def booking_confirmed_email(
    recipient: User,
    other: User,
    club_name: str,
    starts_at: datetime,
    timezone: str,
    duration: int,
    *,
    to_partner: bool,
) -> EmailMessage:
    link = f"{get_settings().public_web_url}/sessions"
    when = _when(starts_at, timezone, duration)
    greeting = f"Hi {recipient.full_name or 'there'},"
    body = (
        f"New session booked: {other.full_name} at {club_name}, {when}."
        if to_partner
        else f"You're booked with {other.full_name} at {club_name}, {when}. "
        "Remember to arrange court access at the venue."
    )
    footer = "Free cancellation up to 12 hours before the session; a 50% fee applies after that."
    return EmailMessage(
        to=recipient.email,
        subject=f"Session confirmed: {when}",
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "View session", link, footer),
    )


def booking_cancelled_email(
    recipient: User,
    cancelled_by: str,
    club_name: str,
    starts_at: datetime,
    timezone: str,
    duration: int,
    reason: str,
) -> EmailMessage:
    link = f"{get_settings().public_web_url}/sessions"
    when = _when(starts_at, timezone, duration)
    greeting = f"Hi {recipient.full_name or 'there'},"
    body = f"Your session at {club_name}, {when}, was cancelled by the {cancelled_by}."
    footer = f"Reason: {reason}" if reason else "You can book another time any time."
    return EmailMessage(
        to=recipient.email,
        subject=f"Session cancelled: {when}",
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "Find another time", link, footer),
    )


def booking_rained_out_email(
    recipient: User, club_name: str, starts_at: datetime, timezone: str, duration: int
) -> EmailMessage:
    link = f"{get_settings().public_web_url}/partners"
    when = _when(starts_at, timezone, duration)
    greeting = f"Hi {recipient.full_name or 'there'},"
    body = f"Your session at {club_name}, {when}, was rained out. You haven't been charged."
    footer = "You have a rebooking credit valid for 30 days."
    return EmailMessage(
        to=recipient.email,
        subject="Rained out — your session is credited",
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "Rebook", link, footer),
    )


def format_money(amount_cents: int, currency: str) -> str:
    symbol = {"usd": "$", "eur": "€", "gbp": "£"}.get(currency.lower())
    value = f"{amount_cents / 100:,.2f}"
    return f"{symbol}{value}" if symbol else f"{value} {currency.upper()}"


def refund_email(recipient: User, amount_cents: int, currency: str) -> EmailMessage:
    link = f"{get_settings().public_web_url}/sessions?scope=past"
    greeting = f"Hi {recipient.full_name or 'there'},"
    body = f"We've refunded {format_money(amount_cents, currency)} to your card."
    footer = "Refunds usually appear on your statement within 5–10 business days."
    return EmailMessage(
        to=recipient.email,
        subject=f"Refund of {format_money(amount_cents, currency)} issued",
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "View sessions", link, footer),
    )


def _local(at: datetime, timezone: str) -> str:
    local = at.astimezone(ZoneInfo(timezone))
    return f"{local:%a %d %b, %H:%M}"


def reminder_email(
    recipient: User, other: User, club: str, starts_at: datetime, timezone: str, *, soon: bool
) -> EmailMessage:
    link = f"{get_settings().public_web_url}/sessions"
    when = _local(starts_at, timezone)
    greeting = f"Hi {recipient.full_name or 'there'},"
    lead = "Starting soon" if soon else "Tomorrow"
    body = f"{lead}: tennis with {other.full_name} at {club}, {when}."
    footer = "Need to cancel? Do it from My sessions (free up to 12 hours before)."
    return EmailMessage(
        to=recipient.email,
        subject=f"{lead}: tennis with {other.full_name}, {when}",
        text=f"{greeting}\n\n{body}\n\n{footer}\n\n{link}\n",
        html=_html(greeting, body, "View session", link, footer),
    )


def follow_up_email(client: User, partner: User) -> EmailMessage:
    link = f"{get_settings().public_web_url}/partners/{partner.id}"
    greeting = f"Hi {client.full_name or 'there'},"
    body = f"Thanks for hitting with {partner.full_name}! Keep the rhythm going — book your next session."
    footer = "Regular sessions are the fastest way to groove your strokes."
    return EmailMessage(
        to=client.email,
        subject=f"Book again with {partner.full_name}?",
        text=f"{greeting}\n\n{body}\n\n{link}\n\n{footer}\n",
        html=_html(greeting, body, f"Book {partner.full_name} again", link, footer),
    )
