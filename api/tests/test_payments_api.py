from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.db import get_sessionmaker
from app.events.envelope import EventEnvelope
from app.events.publisher import InMemoryPublisher
from app.events.registry import dispatch
from app.integrations.payments import FakeGateway, PaymentProviderError, get_gateway
from app.models import Booking, Refund
from tests.test_bookings_api import at, book, pay, ready_client, shift_start

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def checkout(client: AsyncClient, booking_id: str, promo: str | None = None):  # type: ignore[no-untyped-def]
    return await client.post(f"/bookings/{booking_id}/checkout", json={"promo_code": promo})


async def expire(booking_id: str) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(hold_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()


async def refunds() -> list[tuple[int, str, str]]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(select(Refund).order_by(Refund.created_at))
        return [(r.amount_cents, r.reason, r.status.value) for r in rows]


async def test_config(api_client: AsyncClient) -> None:
    body = (await api_client.get("/payments/config")).json()
    assert body == {
        "enabled": True,
        "provider": "fake",
        "publishable_key": None,
        "currency": "usd",
        "prices_cents": {"60": 4500, "90": 6500},
    }


# --- Checkout & confirmation ------------------------------------------------------------


async def test_checkout_prices_and_confirms_on_success(setup, deliver) -> None:
    client, _, partner_id, downtown, _ = setup
    hold = (await book(client, partner_id, downtown, at(3, "08:00"), duration=90)).json()
    assert (hold["price_cents"], hold["paid_cents"]) == (6500, 0)

    started = await checkout(client, hold["id"])

    assert started.status_code == 200
    payment = started.json()["payment"]
    assert (payment["amount_cents"], payment["status"]) == (6500, "requires_payment")
    assert started.json()["client_secret"].startswith("fake_pi_")
    assert started.json()["booking"]["status"] == "held"  # not confirmed until paid

    await client.post(f"/dev-payments/{payment['id']}/succeed")
    await client.post(f"/dev-payments/{payment['id']}/succeed")  # duplicate delivery

    booking = (await client.get(f"/bookings/{hold['id']}")).json()
    assert (booking["status"], booking["paid_cents"]) == ("confirmed", 6500)
    assert await deliver() == ["booking.confirmed"]  # once, despite the duplicate


async def test_failed_card_keeps_the_hold_for_a_retry(setup) -> None:
    client, _, partner_id, downtown, _ = setup
    hold = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    first = (await checkout(client, hold["id"])).json()["payment"]

    await client.post(f"/dev-payments/{first['id']}/fail")

    assert (await client.get(f"/bookings/{hold['id']}")).json()["status"] == "held"
    assert (await pay(client, hold["id"]))["status"] == "confirmed"


async def test_payment_after_lapse_revives_a_free_slot(setup) -> None:
    client, _, partner_id, downtown, _ = setup
    hold = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    payment = (await checkout(client, hold["id"])).json()["payment"]
    await expire(hold["id"])

    await client.post(f"/dev-payments/{payment['id']}/succeed")

    assert (await client.get(f"/bookings/{hold['id']}")).json()["status"] == "confirmed"
    assert await refunds() == []


async def test_payment_after_lapse_for_a_taken_slot_is_refunded(
    make_client: MakeClient, setup, deliver, gateway: FakeGateway
) -> None:
    client, _, partner_id, downtown, _ = setup
    rival = await ready_client(make_client)
    start = at(3, "08:00")
    hold = (await book(client, partner_id, downtown, start)).json()
    payment = (await checkout(client, hold["id"])).json()["payment"]
    await expire(hold["id"])
    await pay(rival, (await book(rival, partner_id, downtown, start)).json()["id"])

    await client.post(f"/dev-payments/{payment['id']}/succeed")

    assert (await client.get(f"/bookings/{hold['id']}")).json()["status"] == "expired"
    assert await refunds() == [(4500, "booking_unavailable", "pending")]
    await deliver()
    assert [amount for _, amount, _ in gateway.refunds] == [4500]
    assert await refunds() == [(4500, "booking_unavailable", "succeeded")]


async def test_cannot_check_out_twice_or_for_others(make_client: MakeClient, setup) -> None:
    client, _, partner_id, downtown, _ = setup
    stranger = await ready_client(make_client)
    hold = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    payment = (await checkout(client, hold["id"])).json()["payment"]

    assert (await checkout(stranger, hold["id"])).status_code == 404
    assert (await stranger.post(f"/dev-payments/{payment['id']}/succeed")).status_code == 404
    await pay(client, hold["id"])
    assert (await checkout(client, hold["id"])).json()["detail"]["code"] == "not_payable"


# --- Refunds ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hours_before", "canceller", "refund"),
    [(None, "client", 4500), (6, "client", 2250), (6, "partner", 4500)],
)
async def test_cancellation_refunds(
    setup, deliver, gateway: FakeGateway, hours_before: int | None, canceller: str, refund: int
) -> None:
    client, partner, partner_id, downtown, _ = setup
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    if hours_before:
        await shift_start(booking["id"], datetime.now(UTC) + timedelta(hours=hours_before))
    actor = client if canceller == "client" else partner

    await actor.post(f"/bookings/{booking['id']}/cancel", json={})
    await deliver()

    assert [amount for _, amount, _ in gateway.refunds] == [refund]
    assert gateway.refunds[0][2].startswith("refund-")  # idempotency key
    assert (await client.get(f"/bookings/{booking['id']}")).json()["refunded_cents"] == refund


async def test_refund_retries_after_provider_errors(
    setup, publisher: InMemoryPublisher, gateway: FakeGateway
) -> None:
    client, _, partner_id, downtown, _ = setup
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    publisher.messages.clear()
    await client.post(f"/bookings/{booking['id']}/cancel", json={})
    message = next(
        m for m in publisher.messages if m[2]["event_type"] == "payment.refund_requested"
    )
    envelope = EventEnvelope.model_validate_json(message[1])

    gateway.fail_refunds = True
    with pytest.raises(PaymentProviderError):
        await dispatch(get_sessionmaker(), envelope)  # Pub/Sub would redeliver
    assert await refunds() == [(4500, "cancellation", "pending")]

    gateway.fail_refunds = False
    await dispatch(get_sessionmaker(), envelope)
    await dispatch(get_sessionmaker(), envelope)  # duplicate delivery: no second refund
    assert len(gateway.refunds) == 1
    assert await refunds() == [(4500, "cancellation", "succeeded")]


# --- Credits ----------------------------------------------------------------------------


async def rained_out_credit(
    make_client: MakeClient, client: AsyncClient, partner_id: str, club: str
) -> None:
    admin = await make_client("admin", admin=True)
    booking = await pay(client, (await book(client, partner_id, club, at(3, "08:00"))).json()["id"])
    await admin.post(f"/admin/bookings/{booking['id']}/rainout", json={})


async def test_rain_out_credit_pays_the_next_booking(
    make_client: MakeClient, setup, gateway
) -> None:
    client, _, partner_id, downtown, _ = setup
    await rained_out_credit(make_client, client, partner_id, downtown)

    credits = (await client.get("/me/credits")).json()
    assert credits["balance_cents"] == 4500
    expires = datetime.fromisoformat(credits["credits"][0]["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)
    assert gateway.refunds == []  # rain-outs are credited, not refunded

    hold = (await book(client, partner_id, downtown, at(4, "08:00"))).json()
    started = (await checkout(client, hold["id"])).json()

    assert started["client_secret"] is None
    assert started["payment"]["credit_applied_cents"] == 4500
    assert started["booking"]["status"] == "confirmed"
    assert (await client.get("/me/credits")).json()["balance_cents"] == 0


async def test_partial_credit_and_split_refund(
    make_client: MakeClient, setup, deliver, gateway
) -> None:
    client, _, partner_id, downtown, _ = setup
    await rained_out_credit(make_client, client, partner_id, downtown)
    hold = (await book(client, partner_id, downtown, at(4, "08:00"), duration=90)).json()

    payment = (await checkout(client, hold["id"])).json()["payment"]
    assert (payment["credit_applied_cents"], payment["amount_cents"]) == (4500, 2000)
    await client.post(f"/dev-payments/{payment['id']}/succeed")
    assert (await client.get("/me/credits")).json()["balance_cents"] == 0

    # Late cancel: 6500 paid, 50% fee → 3250 back: card first (2000), the rest as credit.
    await shift_start(hold["id"], datetime.now(UTC) + timedelta(hours=6))
    await client.post(f"/bookings/{hold['id']}/cancel", json={})
    await deliver()

    assert [amount for _, amount, _ in gateway.refunds] == [2000]
    assert (await client.get("/me/credits")).json()["balance_cents"] == 1250


# --- Promo codes ------------------------------------------------------------------------


async def test_promo_codes(make_client: MakeClient, setup) -> None:
    client, _, partner_id, downtown, _ = setup
    admin = await make_client("admin", admin=True)
    created = await admin.post(
        "/admin/promo-codes",
        json={"code": "intro15", "percent_off": 15, "first_booking_only": True},
    )
    assert created.json()["code"] == "INTRO15"
    assert (
        await admin.post("/admin/promo-codes", json={"code": "INTRO15", "percent_off": 5})
    ).status_code == 409
    assert (
        await client.post("/admin/promo-codes", json={"code": "X1Y", "percent_off": 5})
    ).status_code == 403

    hold = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    bogus = await checkout(client, hold["id"], "NOPE")
    started = (await checkout(client, hold["id"], "Intro15")).json()

    assert bogus.json()["detail"]["code"] == "promo_invalid"
    assert (started["payment"]["discount_cents"], started["payment"]["amount_cents"]) == (675, 3825)
    await client.post(f"/dev-payments/{started['payment']['id']}/succeed")
    booking = (await client.get(f"/bookings/{hold['id']}")).json()
    assert booking["paid_cents"] == 3825  # the discount isn't money paid

    second = (await book(client, partner_id, downtown, at(4, "08:00"))).json()
    reuse = await checkout(client, second["id"], "INTRO15")
    assert reuse.json()["detail"]["code"] == "promo_used"
    codes = (await admin.get("/admin/promo-codes")).json()
    assert codes[0]["redemptions"] == 1


# --- Stripe webhook ---------------------------------------------------------------------


class WebhookGateway(FakeGateway):
    """Fake gateway that accepts webhooks, to exercise the webhook route."""

    def __init__(self) -> None:
        super().__init__()
        self.next_event: dict = {}

    def parse_webhook(self, payload: bytes, signature: str | None) -> dict:
        if signature != "valid":
            from app.integrations.payments import WebhookError

            raise WebhookError("bad signature")
        return self.next_event


async def test_stripe_webhook(setup, deliver, api_client: AsyncClient) -> None:
    from app.main import app

    client, _, partner_id, downtown, _ = setup
    hooks = WebhookGateway()
    app.dependency_overrides[get_gateway] = lambda: hooks
    hold = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    intent = (await checkout(client, hold["id"])).json()["client_secret"].removesuffix("_secret")
    hooks.next_event = {
        "id": "evt_1",
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": intent}},
    }

    rejected = await api_client.post(
        "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "forged"}
    )
    accepted = await api_client.post(
        "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "valid"}
    )
    replayed = await api_client.post(
        "/webhooks/stripe", content=b"{}", headers={"stripe-signature": "valid"}
    )

    assert rejected.status_code == 400
    assert (accepted.status_code, replayed.status_code) == (200, 200)
    assert (await client.get(f"/bookings/{hold['id']}")).json()["status"] == "confirmed"
    assert await deliver() == ["booking.confirmed"]
