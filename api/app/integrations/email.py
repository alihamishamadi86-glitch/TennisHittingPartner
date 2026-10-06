import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str
    html: str


class EmailSender(Protocol):
    async def send(self, message: EmailMessage) -> None: ...


class SmtpEmailSender:
    def __init__(self, host: str, port: int, sender: str) -> None:
        self._host, self._port, self._sender = host, port, sender

    def _send_sync(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"] = self._sender
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        mime.add_alternative(message.html, subtype="html")
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            smtp.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)


class ConsoleEmailSender:
    """Logs emails instead of sending them (staging until a provider is wired in M7)."""

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "Email (console backend) to %s: %s",
            message.to,
            message.subject,
            extra={"extra_fields": {"email_text": message.text}},
        )


class InMemoryEmailSender:
    """Test double."""

    def __init__(self) -> None:
        self.outbox: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.outbox.append(message)


@lru_cache
def get_email_sender() -> EmailSender:
    settings = get_settings()
    if settings.email_backend == "smtp":
        return SmtpEmailSender(settings.smtp_host, settings.smtp_port, settings.email_from)
    return ConsoleEmailSender()
