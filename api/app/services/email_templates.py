from html import escape
from urllib.parse import urlencode

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
