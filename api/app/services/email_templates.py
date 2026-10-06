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
