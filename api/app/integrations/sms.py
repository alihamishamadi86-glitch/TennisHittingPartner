"""Text messages: Twilio in the cloud, a console logger for development."""

import base64
import hashlib
import hmac
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class SmsError(Exception):
    pass


@dataclass(frozen=True)
class SmsMessage:
    to: str  # E.164
    body: str


class SmsSender(Protocol):
    async def send(self, message: SmsMessage) -> None: ...


class TwilioSmsSender:
    def __init__(
        self, account_sid: str, auth_token: str, from_number: str, messaging_service_sid: str
    ) -> None:
        self._sid = account_sid
        self._token = auth_token
        self._from = from_number
        self._service = messaging_service_sid

    async def send(self, message: SmsMessage) -> None:
        data = {"To": message.to, "Body": message.body}
        if self._service:
            data["MessagingServiceSid"] = self._service  # handles STOP/opt-out at Twilio too
        else:
            data["From"] = self._from
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self._sid}/Messages.json"
        async with httpx.AsyncClient(timeout=15, auth=(self._sid, self._token)) as client:
            response = await client.post(url, data=data)
        if response.status_code >= 400:
            raise SmsError(f"Twilio rejected SMS ({response.status_code}): {response.text[:200]}")


class ConsoleSmsSender:
    async def send(self, message: SmsMessage) -> None:
        logger.info("SMS (console backend) to %s: %s", message.to, message.body)


class InMemorySmsSender:
    """Test double."""

    def __init__(self) -> None:
        self.outbox: list[SmsMessage] = []

    async def send(self, message: SmsMessage) -> None:
        self.outbox.append(message)


def twilio_signature_valid(
    url: str, params: Mapping[str, str], signature: str | None, auth_token: str
) -> bool:
    """Twilio request validation: HMAC-SHA1 over the URL plus sorted form params."""
    if not signature or not auth_token:
        return False
    payload = url + "".join(f"{key}{params[key]}" for key in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


@lru_cache
def get_sms_sender() -> SmsSender:
    settings = get_settings()
    if settings.sms_backend == "twilio":
        return TwilioSmsSender(
            settings.twilio_account_sid,
            settings.twilio_auth_token.get_secret_value(),
            settings.twilio_from_number,
            settings.twilio_messaging_service_sid,
        )
    return ConsoleSmsSender()
