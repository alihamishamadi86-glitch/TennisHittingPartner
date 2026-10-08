"""Payment gateway: Stripe in the cloud, a fake for local development and tests.

Only PaymentIntents are used (embedded Payment Element, no redirect). Every mutating call
carries an idempotency key derived from our own row ids, so retries never double-charge or
double-refund.
"""

import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import stripe

from app.core.config import get_settings


class PaymentProviderError(Exception):
    """Provider unavailable or rejected the request (worth retrying unless stated)."""


class WebhookError(Exception):
    """Webhook signature or payload invalid."""


@dataclass(frozen=True)
class Intent:
    id: str
    client_secret: str


class PaymentGateway(Protocol):
    name: str

    async def create_intent(
        self, *, amount_cents: int, currency: str, metadata: dict[str, str], idempotency_key: str
    ) -> Intent: ...

    async def cancel_intent(self, intent_id: str) -> None: ...

    async def refund(self, *, intent_id: str, amount_cents: int, idempotency_key: str) -> str: ...

    def parse_webhook(self, payload: bytes, signature: str | None) -> dict[str, Any]: ...


class StripeGateway:
    name = "stripe"

    def __init__(self, secret_key: str, webhook_secret: str) -> None:
        self._client = stripe.StripeClient(secret_key, http_client=stripe.HTTPXClient())
        self._webhook_secret = webhook_secret

    async def create_intent(
        self, *, amount_cents: int, currency: str, metadata: dict[str, str], idempotency_key: str
    ) -> Intent:
        try:
            intent = await self._client.v1.payment_intents.create_async(
                params={
                    "amount": amount_cents,
                    "currency": currency,
                    "metadata": metadata,
                    "automatic_payment_methods": {"enabled": True},
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return Intent(intent.id, intent.client_secret or "")

    async def cancel_intent(self, intent_id: str) -> None:
        try:
            await self._client.v1.payment_intents.cancel_async(intent_id)
        except stripe.InvalidRequestError:
            pass  # already succeeded/canceled: nothing to cancel
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc

    async def refund(self, *, intent_id: str, amount_cents: int, idempotency_key: str) -> str:
        try:
            refund = await self._client.v1.refunds.create_async(
                params={"payment_intent": intent_id, "amount": amount_cents},
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return refund.id

    def parse_webhook(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        try:
            event = self._client.construct_event(payload, signature, self._webhook_secret)
        except (ValueError, stripe.SignatureVerificationError) as exc:
            raise WebhookError(str(exc)) from exc
        result: dict[str, Any] = event.to_dict()
        return result


class FakeGateway:
    """Simulates Stripe locally: intents are paid via POST /dev-payments/{id}/succeed."""

    name = "fake"

    def __init__(self) -> None:
        self.refunds: list[tuple[str, int, str]] = []
        self.canceled: list[str] = []
        self.fail_refunds = False

    async def create_intent(
        self, *, amount_cents: int, currency: str, metadata: dict[str, str], idempotency_key: str
    ) -> Intent:
        intent_id = f"fake_pi_{uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex}"
        return Intent(intent_id, f"{intent_id}_secret")

    async def cancel_intent(self, intent_id: str) -> None:
        self.canceled.append(intent_id)

    async def refund(self, *, intent_id: str, amount_cents: int, idempotency_key: str) -> str:
        if self.fail_refunds:
            raise PaymentProviderError("simulated refund failure")
        self.refunds.append((intent_id, amount_cents, idempotency_key))
        return f"fake_re_{uuid.uuid5(uuid.NAMESPACE_URL, idempotency_key).hex}"

    def parse_webhook(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        raise WebhookError("The fake gateway doesn't receive webhooks")


@lru_cache
def get_gateway() -> PaymentGateway:
    settings = get_settings()
    if settings.payment_provider == "stripe":
        return StripeGateway(
            settings.stripe_secret_key.get_secret_value().strip(),
            settings.stripe_webhook_secret.get_secret_value().strip(),
        )
    return FakeGateway()
