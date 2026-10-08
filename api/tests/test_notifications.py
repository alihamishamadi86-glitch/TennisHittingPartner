import base64
import hashlib
import hmac
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.integrations.email import InMemoryEmailSender
from app.integrations.sms import InMemorySmsSender
from app.models import NotificationKind, PhoneVerification, ScheduledNotification
from app.services import notifications
from tests.test_bookings_api import at, book, pay, ready_client, shift_start

MakeClient = Callable[..., Awaitable[AsyncClient]]


def last_code(sms: InMemorySmsSender) -> str:
    match = re.search(r"\b(\d{6})\b", sms.outbox[-1].body)
    assert match
    return match.group(1)


async def verified_with_sms(client: AsyncClient, sms: InMemorySmsSender, phone: str) -> None:
    assert (await client.post("/me/phone", json={"phone": phone})).status_code == 202
    assert (await client.post("/me/phone/verify", json={"code": last_code(sms)})).status_code == 200
    on = await client.put(
        "/me/notifications", json={"sms_reminders": True, "email_reminders": True}
    )
    assert on.json()["sms_reminders"] is True


# --- Phone verification -----------------------------------------------------------------


async def test_phone_verification(make_client: MakeClient, sms_sender: InMemorySmsSender) -> None:
    client = await ready_client(make_client)  # US profile

    sent = await client.post("/me/phone", json={"phone": "(512) 555-0123"})
    wrong = await client.post("/me/phone/verify", json={"code": "000000"})
    right = await client.post("/me/phone/verify", json={"code": last_code(sms_sender)})

    assert sent.json() == {"phone": "+15125550123"}
    assert sms_sender.outbox[0].to == "+15125550123"
    assert wrong.json()["detail"]["code"] == "wrong_code"
    assert right.json() == {
        "sms_available": True,
        "phone": "+15125550123",
        "phone_verified": True,
        "sms_reminders": False,  # verifying isn't consent
        "email_reminders": True,
    }


async def test_phone_validation_and_limits(make_client: MakeClient, sms_sender) -> None:
    client = await ready_client(make_client)
    assert (await client.post("/me/phone", json={"phone": "12345"})).json()["detail"][
        "code"
    ] == "invalid_phone"
    landline = await client.post("/me/phone", json={"phone": "+34 963 28 91 40"})
    assert landline.json()["detail"]["code"] == "not_mobile"
    for _ in range(5):
        await client.post("/me/phone", json={"phone": "512 555 0123"})
    assert (await client.post("/me/phone", json={"phone": "512 555 0123"})).status_code == 429


async def test_expired_and_exhausted_codes(make_client: MakeClient, sms_sender) -> None:
    client = await ready_client(make_client)
    await client.post("/me/phone", json={"phone": "512 555 0123"})
    for _ in range(5):
        await client.post("/me/phone/verify", json={"code": "000000"})
    exhausted = await client.post("/me/phone/verify", json={"code": last_code(sms_sender)})
    assert exhausted.json()["detail"]["code"] == "too_many_attempts"

    await client.post("/me/phone", json={"phone": "512 555 0123"})
    async with get_sessionmaker()() as session:
        await session.execute(
            update(PhoneVerification).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    expired = await client.post("/me/phone/verify", json={"code": last_code(sms_sender)})
    assert expired.json()["detail"]["code"] == "code_expired"


async def test_sms_reminders_need_a_verified_phone(make_client: MakeClient, sms_sender) -> None:
    client = await ready_client(make_client)
    refused = await client.put(
        "/me/notifications", json={"sms_reminders": True, "email_reminders": False}
    )
    assert refused.json()["detail"]["code"] == "phone_required"
    await verified_with_sms(client, sms_sender, "512 555 0123")
    removed = await client.delete("/me/phone")
    assert removed.json()["sms_reminders"] is False and removed.json()["phone"] is None


# --- Scheduling & sending ---------------------------------------------------------------


async def scheduled(booking_id: str) -> dict[NotificationKind, ScheduledNotification]:
    async with get_sessionmaker()() as session:
        rows = await session.scalars(
            select(ScheduledNotification).where(ScheduledNotification.booking_id == booking_id)
        )
        return {row.kind: row for row in rows}


async def make_due(booking_id: str, kind: NotificationKind) -> None:
    async with get_sessionmaker()() as session:
        await session.execute(
            update(ScheduledNotification)
            .where(
                ScheduledNotification.booking_id == booking_id, ScheduledNotification.kind == kind
            )
            .values(send_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()


async def sweep(email: InMemoryEmailSender, sms: InMemorySmsSender) -> int:
    async with get_sessionmaker()() as session, session.begin():
        return await notifications.send_due(session, email, sms)


@pytest.fixture
def daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notifications, "quiet", lambda at, tz: False)


async def test_confirmation_schedules_reminders_and_texts_the_partner(
    setup, deliver, sms_sender: InMemorySmsSender, daytime, monkeypatch
) -> None:
    monkeypatch.setattr("app.events.handlers.bookings.quiet", lambda at, tz: False)
    client, partner, partner_id, downtown, _ = setup
    await verified_with_sms(partner, sms_sender, "512 555 0199")
    sms_sender.outbox.clear()

    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    await deliver()

    rows = await scheduled(booking["id"])
    start = datetime.fromisoformat(booking["starts_at"])
    assert rows[NotificationKind.REMINDER_24H].send_at == start - timedelta(hours=24)
    assert rows[NotificationKind.REMINDER_2H].send_at == start - timedelta(hours=2)
    assert rows[NotificationKind.FOLLOW_UP].send_at >= start + timedelta(hours=2)
    assert [m.to for m in sms_sender.outbox] == ["+15125550199"]
    assert sms_sender.outbox[0].body.startswith("New session: Client User")


async def test_reminders_respect_preferences_and_send_once(
    setup, deliver, email_sender: InMemoryEmailSender, sms_sender: InMemorySmsSender, daytime
) -> None:
    client, partner, partner_id, downtown, _ = setup
    await verified_with_sms(client, sms_sender, "512 555 0123")
    await partner.put("/me/notifications", json={"sms_reminders": False, "email_reminders": False})
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    await deliver()
    email_sender.outbox.clear()
    sms_sender.outbox.clear()
    await make_due(booking["id"], NotificationKind.REMINDER_24H)

    assert await sweep(email_sender, sms_sender) == 1
    assert await sweep(email_sender, sms_sender) == 0  # at most once

    assert [m.to for m in email_sender.outbox] == ["client-1@example.com"]  # partner opted out
    assert email_sender.outbox[0].subject.startswith("Tomorrow: tennis with Partner User")
    assert [m.to for m in sms_sender.outbox] == ["+15125550123"]
    assert "Austin Tennis Center" in sms_sender.outbox[0].body
    assert (await scheduled(booking["id"]))[NotificationKind.REMINDER_24H].detail == "email,sms"


async def test_no_texts_at_night(setup, deliver, email_sender, sms_sender, monkeypatch) -> None:
    client, _, partner_id, downtown, _ = setup
    await verified_with_sms(client, sms_sender, "512 555 0123")
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    await deliver()
    sms_sender.outbox.clear()
    monkeypatch.setattr(notifications, "quiet", lambda at, tz: True)
    await make_due(booking["id"], NotificationKind.REMINDER_2H)

    await sweep(email_sender, sms_sender)
    assert sms_sender.outbox == []
    assert any(m.subject.startswith("Starting soon") for m in email_sender.outbox)


async def test_cancelled_sessions_get_no_reminder(setup, deliver, email_sender, sms_sender) -> None:
    client, _, partner_id, downtown, _ = setup
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    await deliver()
    await client.post(f"/bookings/{booking['id']}/cancel", json={})
    email_sender.outbox.clear()
    await make_due(booking["id"], NotificationKind.REMINDER_24H)

    await sweep(email_sender, sms_sender)
    assert email_sender.outbox == []
    assert (await scheduled(booking["id"]))[NotificationKind.REMINDER_24H].status.value == "skipped"


async def test_follow_up_after_the_session(
    setup, deliver, email_sender, sms_sender, daytime
) -> None:
    client, partner, partner_id, downtown, _ = setup
    booking = await pay(
        client, (await book(client, partner_id, downtown, at(3, "08:00"))).json()["id"]
    )
    await deliver()
    await shift_start(booking["id"], datetime.now(UTC) - timedelta(hours=2))
    await partner.post(f"/bookings/{booking['id']}/complete")
    email_sender.outbox.clear()
    await make_due(booking["id"], NotificationKind.FOLLOW_UP)

    await sweep(email_sender, sms_sender)
    assert [m.to for m in email_sender.outbox] == ["client-1@example.com"]
    assert f"/partners/{partner_id}" in email_sender.outbox[0].text


def test_quiet_hours_shift_to_the_morning() -> None:
    tz = "America/Chicago"
    from zoneinfo import ZoneInfo

    chicago = ZoneInfo(tz)
    night = datetime(2026, 10, 12, 22, 0, tzinfo=chicago)
    small_hours = datetime(2026, 10, 13, 3, 0, tzinfo=chicago)
    day = datetime(2026, 10, 13, 10, 0, tzinfo=chicago)
    morning = datetime(2026, 10, 13, 8, 0, tzinfo=chicago)
    assert notifications.after_quiet_hours(night, tz) == morning
    assert notifications.after_quiet_hours(small_hours, tz) == morning
    assert notifications.after_quiet_hours(day, tz) == day


# --- Twilio STOP ------------------------------------------------------------------------


def twilio_sign(url: str, params: dict[str, str], token: str) -> str:
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    return base64.b64encode(
        hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()


async def test_stop_reply_turns_texts_off(
    make_client: MakeClient, sms_sender, api_client: AsyncClient
) -> None:
    from app.main import app

    client = await ready_client(make_client)
    await verified_with_sms(client, sms_sender, "512 555 0123")
    app.dependency_overrides[get_settings] = lambda: Settings(twilio_auth_token="tok")  # type: ignore[call-arg]
    url = "http://api/webhooks/twilio/sms"
    params = {"From": "+15125550123", "Body": " stop "}
    try:
        forged = await api_client.post(url, data=params, headers={"X-Twilio-Signature": "nope"})
        genuine = await api_client.post(
            url, data=params, headers={"X-Twilio-Signature": twilio_sign(url, params, "tok")}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert forged.status_code == 403
    assert genuine.status_code == 200
    assert (await client.get("/me/notifications")).json()["sms_reminders"] is False
