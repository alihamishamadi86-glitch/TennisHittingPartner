"""PAYMENTS_ENABLED / SMS_ENABLED switched off (the default outside tests)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.integrations.email import InMemoryEmailSender
from app.integrations.sms import InMemorySmsSender
from app.models import Payment, ScheduledNotification, User
from tests.test_bookings_api import at, book, ready_client
from tests.test_notifications import MakeClient


@pytest.fixture
def flags_off(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("PAYMENTS_ENABLED", "false")
    monkeypatch.setenv("SMS_ENABLED", "false")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


def test_flags_default_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PAYMENTS_ENABLED")
    monkeypatch.delenv("SMS_ENABLED")
    settings = type(get_settings())(_env_file=None)  # type: ignore[call-arg]
    assert settings.payments_enabled is False
    assert settings.sms_enabled is False


async def test_bookings_confirm_without_payment(
    flags_off, setup, deliver, email_sender: InMemoryEmailSender
) -> None:
    client, _, partner_id, downtown, _ = setup

    config = (await client.get("/payments/config")).json()
    created = await book(client, partner_id, downtown, at(3, "08:00"))
    booking = created.json()
    checkout = await client.post(f"/bookings/{booking['id']}/checkout", json={})
    await deliver()

    assert config["enabled"] is False
    assert created.status_code == 201, created.text
    assert booking["status"] == "confirmed"
    assert booking["hold_expires_at"] is None and booking["confirmed_at"]
    assert checkout.status_code == 404
    async with get_sessionmaker()() as session:
        assert (await session.scalars(select(Payment))).all() == []
        reminders = (await session.scalars(select(ScheduledNotification))).all()
    assert len(reminders) == 3  # confirmation still schedules reminders
    assert email_sender.outbox  # and emails both people

    cancelled = await client.post(f"/bookings/{booking['id']}/cancel", json={"reason": "Busy"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["refunded_cents"] == 0


async def test_sms_switched_off(
    flags_off, make_client: MakeClient, sms_sender: InMemorySmsSender
) -> None:
    client = await ready_client(make_client)
    me = (await client.get("/me")).json()
    # A number verified while SMS was on stays on file but gets no texts.
    async with get_sessionmaker()() as session:
        user = await session.get(User, me["id"])
        assert user
        user.phone = "+15125550123"
        user.phone_verified_at = user.created_at
        user.sms_opt_in_at = user.created_at
        await session.commit()

    prefs = await client.get("/me/notifications")
    add = await client.post("/me/phone", json={"phone": "512 555 0123"})
    verify = await client.post("/me/phone/verify", json={"code": "123456"})
    turn_on = await client.put(
        "/me/notifications", json={"sms_reminders": True, "email_reminders": True}
    )

    assert prefs.json()["sms_available"] is False
    assert prefs.json()["sms_reminders"] is False
    assert add.status_code == verify.status_code == 404
    assert turn_on.json()["detail"]["code"] == "sms_disabled"
    assert sms_sender.outbox == []
