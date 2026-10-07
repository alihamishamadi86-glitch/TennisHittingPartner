import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.core.db import get_sessionmaker
from app.integrations.email import InMemoryEmailSender
from app.models import Booking, BookingStatus, User
from tests.test_availability_api import CHICAGO, club_ids, local_today, make_partner
from tests.test_profiles import CLIENT_PROFILE

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def ready_client(make_client: MakeClient, *, sign: bool = True) -> AsyncClient:
    """A client who may book: verified email, profile, signed waiver."""
    client = await make_client("client")
    me = (await client.get("/me")).json()
    async with get_sessionmaker()() as session:
        await session.execute(
            update(User).where(User.id == me["id"]).values(email_verified_at=datetime.now(UTC))
        )
        await session.commit()
    await client.put("/me/client-profile", json=CLIENT_PROFILE)
    if sign:
        signed = await client.post(
            "/waiver/sign", json={"full_name": me["full_name"], "agree": True}
        )
        assert signed.status_code == 200, signed.text
    return client


def at(days: int, hhmm: str) -> datetime:
    day = local_today() + timedelta(days=days)
    hour, minute = map(int, hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=CHICAGO)


async def book(client: AsyncClient, partner_id: str, club_id: str, start: datetime, duration=60):  # type: ignore[no-untyped-def]
    return await client.post(
        "/bookings",
        json={
            "partner_id": partner_id,
            "club_id": club_id,
            "starts_at": start.isoformat(),
            "duration_minutes": duration,
        },
    )


async def shift_start(booking_id: str, starts_at: datetime) -> None:
    """Time travel: move a booking (tests can't wait for real time to pass)."""
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Booking)
            .where(Booking.id == booking_id)
            .values(
                starts_at=starts_at,
                ends_at=starts_at + timedelta(hours=1),
                blocked_until=starts_at + timedelta(minutes=90),
            )
        )
        await session.commit()


@pytest.fixture
async def setup(make_client: MakeClient, geocoder, sources, deliver):  # type: ignore[no-untyped-def]
    client = await ready_client(make_client)
    downtown, north = await club_ids(client, deliver)
    partner, partner_id = await make_partner(
        make_client,
        [downtown],
        schedule=[{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(7)],
    )
    await deliver()
    return client, partner, partner_id, downtown, north


# --- Waiver -----------------------------------------------------------------------------


async def test_waiver_signing(make_client: MakeClient) -> None:
    client = await ready_client(make_client, sign=False)
    waiver = (await client.get("/waiver")).json()
    assert (waiver["version"], waiver["signed"]) == (1, False)
    assert "Release" in waiver["body"]

    wrong_name = await client.post(
        "/waiver/sign", json={"full_name": "Someone Else", "agree": True}
    )
    not_agreed = await client.post(
        "/waiver/sign", json={"full_name": "Client User", "agree": False}
    )
    signed = await client.post("/waiver/sign", json={"full_name": "  client user ", "agree": True})
    again = await client.post("/waiver/sign", json={"full_name": "Client User", "agree": True})

    assert wrong_name.status_code == 422
    assert not_agreed.status_code == 422
    assert signed.json()["signed"] is True
    assert again.status_code == 200


# --- Gates ------------------------------------------------------------------------------


async def test_booking_requires_verified_email_profile_and_waiver(
    make_client: MakeClient, setup
) -> None:
    _, _, partner_id, downtown, _ = setup
    start = at(3, "08:00")

    unverified = await make_client("client")
    no_waiver = await ready_client(make_client, sign=False)

    r1 = await book(unverified, partner_id, downtown, start)
    r2 = await book(no_waiver, partner_id, downtown, start)
    assert r1.json()["detail"]["code"] == "email_unverified"
    assert r2.json()["detail"]["code"] == "waiver_required"
    assert {r1.status_code, r2.status_code} == {409}


async def test_partners_cannot_book(setup) -> None:
    _, partner, partner_id, downtown, _ = setup
    assert (await book(partner, partner_id, downtown, at(3, "08:00"))).status_code == 403


# --- Hold → confirm ---------------------------------------------------------------------


async def test_hold_then_confirm(setup, deliver, email_sender: InMemoryEmailSender) -> None:
    client, partner, partner_id, downtown, _ = setup
    start = at(3, "08:00")

    held = await book(client, partner_id, downtown, start)

    assert held.status_code == 201, held.text
    body = held.json()
    assert body["status"] == "held"
    assert sorted(body["actions"]) == ["cancel", "confirm"]
    expires = datetime.fromisoformat(body["hold_expires_at"])
    assert timedelta(minutes=9) < expires - datetime.now(UTC) <= timedelta(minutes=10)
    assert body["club"]["name"] == "Austin Tennis Center"
    assert body["partner"]["ntrp_rating"] == 4.5

    # The held time (plus buffer) is gone from the partner's open slots.
    slots = (await client.get(f"/partners/{partner_id}/slots", params={"days": 5})).json()
    day = next(d for d in slots["days"] if d["date"] == start.date().isoformat())
    local = [datetime.fromisoformat(s).astimezone(CHICAGO).strftime("%H:%M") for s in day["slots"]]
    assert local == ["09:30", "10:00", "10:30", "11:00"]  # 08:00 taken; 08:30/09:00 in buffer

    confirmed = await client.post(f"/bookings/{body['id']}/confirm")
    assert confirmed.json()["status"] == "confirmed"
    assert confirmed.json()["actions"] == ["cancel"]
    assert confirmed.json()["cancellation_terms"]["fee_fraction_if_cancelled_now"] == 0

    email_sender.outbox.clear()
    assert await deliver() == ["booking.confirmed"]
    assert sorted(m.to for m in email_sender.outbox) == [
        "client-1@example.com",
        "partner-2@example.com",
    ]
    assert "Austin Tennis Center" in email_sender.outbox[0].text

    client_view = (await client.get("/bookings")).json()
    partner_view = (await partner.get("/bookings")).json()
    assert [b["id"] for b in client_view] == [body["id"]]
    assert [b["id"] for b in partner_view] == [body["id"]]
    assert partner_view[0]["actions"] == ["cancel"]


async def test_invalid_requests(setup) -> None:
    client, _, partner_id, downtown, north = setup
    outside_hours = await book(client, partner_id, downtown, at(3, "15:00"))
    misaligned = await book(client, partner_id, downtown, at(3, "08:10"))
    wrong_club = await book(client, partner_id, north, at(3, "08:00"))
    bad_duration = await book(client, partner_id, downtown, at(3, "08:00"), duration=45)

    assert outside_hours.json()["detail"]["code"] == "slot_unavailable"
    assert misaligned.json()["detail"]["code"] == "slot_unavailable"
    assert wrong_club.json()["detail"]["code"] == "invalid_club"
    assert bad_duration.json()["detail"]["code"] == "invalid_duration"


# --- No double-booking ------------------------------------------------------------------


async def test_concurrent_clients_cannot_take_the_same_slot(make_client: MakeClient, setup) -> None:
    client, _, partner_id, downtown, _ = setup
    rival = await ready_client(make_client)
    start = at(4, "09:00")

    first, second = await asyncio.gather(
        book(client, partner_id, downtown, start), book(rival, partner_id, downtown, start)
    )

    codes = sorted([first.status_code, second.status_code])
    assert codes == [201, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["detail"]["code"] in {"slot_taken", "slot_unavailable"}


async def test_database_rejects_overlaps_inside_the_buffer(setup) -> None:
    """The exclusion constraint is the final guard, independent of API checks."""
    client, _, partner_id, downtown, _ = setup
    first = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    async with get_sessionmaker()() as session:
        session.add(
            Booking(
                client_id=first["client"]["id"],
                partner_id=partner_id,
                club_id=downtown,
                starts_at=at(3, "09:15"),  # after the session but inside the 30 min buffer
                ends_at=at(3, "10:15"),
                blocked_until=at(3, "10:45"),
                duration_minutes=60,
                timezone="America/Chicago",
                status=BookingStatus.CONFIRMED,
            )
        )
        with pytest.raises(IntegrityError, match="ex_bookings_partner_time"):
            await session.commit()


async def test_client_cannot_be_in_two_places(make_client: MakeClient, setup, deliver) -> None:
    client, _, partner_id, downtown, _ = setup
    _, other_partner = await make_partner(
        make_client,
        [downtown],
        schedule=[{"weekday": d, "start": "08:00", "end": "12:00"} for d in range(7)],
    )
    await book(client, partner_id, downtown, at(5, "10:00"))

    clash = await book(client, other_partner, downtown, at(5, "10:30"))

    assert clash.status_code == 409
    assert clash.json()["detail"]["code"] == "client_overlap"


# --- Hold expiry ------------------------------------------------------------------------


async def test_expired_hold_frees_the_slot(make_client: MakeClient, setup, worker_client) -> None:
    client, _, partner_id, downtown, _ = setup
    rival = await ready_client(make_client)
    start = at(3, "10:00")
    hold = (await book(client, partner_id, downtown, start)).json()
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Booking)
            .where(Booking.id == hold["id"])
            .values(hold_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()

    late_confirm = await client.post(f"/bookings/{hold['id']}/confirm")
    rival_hold = await book(rival, partner_id, downtown, start)  # lazy expiry frees it

    assert late_confirm.status_code == 409
    assert "expired" in late_confirm.json()["detail"]["message"]
    assert rival_hold.status_code == 201
    assert (await client.get(f"/bookings/{hold['id']}")).json()["status"] == "expired"
    assert (await worker_client.post("/tasks/expire-holds")).json() == {"expired": 0}


async def test_sweep_expires_lapsed_holds(setup, worker_client) -> None:
    client, _, partner_id, downtown, _ = setup
    hold = (await book(client, partner_id, downtown, at(3, "10:00"))).json()
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Booking)
            .where(Booking.id == hold["id"])
            .values(hold_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    assert (await worker_client.post("/tasks/expire-holds")).json() == {"expired": 1}


# --- Cancellation -----------------------------------------------------------------------


async def confirmed(client: AsyncClient, partner_id: str, club: str, start: datetime) -> dict:  # type: ignore[type-arg]
    booking = (await book(client, partner_id, club, start)).json()
    return (await client.post(f"/bookings/{booking['id']}/confirm")).json()


async def test_client_cancels_in_time_for_free(setup, deliver, email_sender) -> None:
    client, _, partner_id, downtown, _ = setup
    booking = await confirmed(client, partner_id, downtown, at(3, "08:00"))
    await deliver()
    email_sender.outbox.clear()

    cancelled = await client.post(f"/bookings/{booking['id']}/cancel", json={"reason": "Sick"})

    assert cancelled.json()["status"] == "cancelled_free"
    assert cancelled.json()["cancellation_fee_fraction"] == 0
    assert await deliver() == ["booking.cancelled"]
    assert [m.to for m in email_sender.outbox] == ["partner-2@example.com"]
    assert "Sick" in email_sender.outbox[0].text
    past = (await client.get("/bookings", params={"scope": "past"})).json()
    assert [b["id"] for b in past] == [booking["id"]]


async def test_late_client_cancellation_has_a_fee(setup) -> None:
    client, _, partner_id, downtown, _ = setup
    booking = await confirmed(client, partner_id, downtown, at(3, "08:00"))
    await shift_start(booking["id"], datetime.now(UTC) + timedelta(hours=6))

    view = (await client.get(f"/bookings/{booking['id']}")).json()
    cancelled = await client.post(f"/bookings/{booking['id']}/cancel", json={})

    assert view["cancellation_terms"]["fee_fraction_if_cancelled_now"] == 0.5
    assert cancelled.json()["status"] == "cancelled_late"
    assert cancelled.json()["cancellation_fee_fraction"] == 0.5


async def test_partner_cancellation_notifies_client(setup, deliver, email_sender) -> None:
    client, partner, partner_id, downtown, _ = setup
    booking = await confirmed(client, partner_id, downtown, at(3, "08:00"))
    await deliver()
    email_sender.outbox.clear()

    cancelled = await partner.post(f"/bookings/{booking['id']}/cancel", json={"reason": "Injury"})

    assert cancelled.json()["status"] == "partner_cancelled"
    await deliver()
    assert [m.to for m in email_sender.outbox] == ["client-1@example.com"]


# --- After the session ------------------------------------------------------------------


async def test_outcomes_after_start(setup) -> None:
    client, partner, partner_id, downtown, _ = setup
    booking = await confirmed(client, partner_id, downtown, at(3, "08:00"))

    too_early = await partner.post(f"/bookings/{booking['id']}/complete")
    await shift_start(booking["id"], datetime.now(UTC) - timedelta(minutes=30))
    client_cancel = await client.post(f"/bookings/{booking['id']}/cancel", json={})
    completed = await partner.post(f"/bookings/{booking['id']}/complete")
    again = await partner.post(f"/bookings/{booking['id']}/no-show")

    assert too_early.status_code == 409
    assert client_cancel.status_code == 409
    assert completed.json()["status"] == "completed"
    assert again.status_code == 409


async def test_admin_rain_out(make_client: MakeClient, setup, deliver, email_sender) -> None:
    client, _, partner_id, downtown, _ = setup
    admin = await make_client("admin", admin=True)
    booking = await confirmed(client, partner_id, downtown, at(3, "08:00"))
    await deliver()
    email_sender.outbox.clear()

    rained = await admin.post(f"/admin/bookings/{booking['id']}/rainout", json={})

    assert rained.json()["status"] == "rained_out"
    assert rained.json()["credit_issued"] is True
    assert await deliver() == ["booking.rained_out"]
    assert email_sender.outbox[0].to == "client-1@example.com"
    assert (
        await client.post(f"/admin/bookings/{booking['id']}/rainout", json={})
    ).status_code == 403


async def test_outsiders_cannot_see_bookings(make_client: MakeClient, setup) -> None:
    client, _, partner_id, downtown, _ = setup
    booking = (await book(client, partner_id, downtown, at(3, "08:00"))).json()
    stranger = await ready_client(make_client)
    assert (await stranger.get(f"/bookings/{booking['id']}")).status_code == 404
    assert (await stranger.post(f"/bookings/{booking['id']}/cancel", json={})).status_code == 404
