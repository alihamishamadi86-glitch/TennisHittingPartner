from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.db import get_sessionmaker
from app.models import PartnerProfile, PartnerStatus
from tests.test_club_merge import BASE_LAT, BASE_LON
from tests.test_clubs_api import discover
from tests.test_profiles import PARTNER_PROFILE

MakeClient = Callable[..., Awaitable[AsyncClient]]
CHICAGO = ZoneInfo("America/Chicago")
EVERY_MORNING = [{"weekday": d, "start": "08:00", "end": "10:00"} for d in range(7)]


def local_today() -> date:
    return datetime.now(UTC).astimezone(CHICAGO).date()


async def club_ids(client: AsyncClient, deliver) -> list[str]:  # type: ignore[no-untyped-def]
    """Discover the fake Austin clubs (see test_clubs_api) and return their ids by name."""
    city = (await discover(client)).json()["city"]
    await deliver()
    clubs = (await client.get("/clubs", params={"city_id": city["id"]})).json()
    return [c["id"] for c in clubs]  # [Austin Tennis Center (downtown), Tennis courts (north)]


async def make_partner(  # type: ignore[no-untyped-def]
    make_client: MakeClient,
    clubs: list[str],
    *,
    level: float | None = 4.5,
    approved: bool = True,
    schedule: list[dict] | None = EVERY_MORNING,
) -> tuple[AsyncClient, str]:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    await partner.put("/me/clubs", json={"club_ids": clubs})
    if schedule is not None:
        saved = await partner.put(
            "/me/availability", json={"timezone": "America/Chicago", "windows": schedule}
        )
        assert saved.status_code == 200, saved.text
    partner_id = (await partner.get("/me")).json()["id"]
    if approved:
        async with get_sessionmaker()() as session:
            await session.execute(
                update(PartnerProfile)
                .where(PartnerProfile.user_id == partner_id)
                .values(status=PartnerStatus.APPROVED, verified_ntrp_rating=level)
            )
            await session.commit()
    return partner, partner_id


# --- Partner: editing -------------------------------------------------------------------


async def test_weekly_schedule_round_trip(make_client: MakeClient) -> None:
    partner = await make_client("partner")
    assert (await partner.get("/me/availability")).status_code == 409  # no profile yet
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)

    saved = await partner.put(
        "/me/availability",
        json={
            "timezone": "Europe/Madrid",
            "windows": [
                {"weekday": 0, "start": "18:00", "end": "24:00"},
                {"weekday": 0, "start": "07:00", "end": "09:30"},
            ],
        },
    )

    assert saved.status_code == 200
    body = saved.json()
    assert body["timezone"] == "Europe/Madrid"
    assert body["windows"] == [
        {"weekday": 0, "start": "07:00", "end": "09:30"},
        {"weekday": 0, "start": "18:00", "end": "24:00"},
    ]
    assert (await partner.get("/me/availability")).json() == body


@pytest.mark.parametrize(
    ("timezone", "windows"),
    [
        ("Mars/Olympus", [{"weekday": 0, "start": "07:00", "end": "08:00"}]),
        ("UTC", [{"weekday": 0, "start": "07:10", "end": "08:00"}]),
        ("UTC", [{"weekday": 0, "start": "09:00", "end": "08:00"}]),
        ("UTC", [{"weekday": 7, "start": "07:00", "end": "08:00"}]),
        ("UTC", [{"weekday": 0, "start": "07:00", "end": "25:00"}]),
        (
            "UTC",
            [
                {"weekday": 2, "start": "07:00", "end": "09:00"},
                {"weekday": 2, "start": "08:30", "end": "10:00"},
            ],
        ),
    ],
)
async def test_invalid_schedules_are_rejected(
    make_client: MakeClient, timezone: str, windows: list[dict]
) -> None:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    response = await partner.put(
        "/me/availability", json={"timezone": timezone, "windows": windows}
    )
    assert response.status_code == 422


async def test_only_partners_manage_availability(make_client: MakeClient) -> None:
    client = await make_client("client")
    assert (await client.get("/me/availability")).status_code == 403


async def test_exceptions_change_the_preview(make_client: MakeClient) -> None:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    await partner.put(
        "/me/availability", json={"timezone": "America/Chicago", "windows": EVERY_MORNING}
    )
    day_off = local_today() + timedelta(days=3)

    before = (await partner.get("/me/availability/preview", params={"days": 7})).json()
    added = await partner.post(
        "/me/availability/exceptions",
        json={"date": day_off.isoformat(), "kind": "unavailable", "note": "Tournament"},
    )
    after = (await partner.get("/me/availability/preview", params={"days": 7})).json()

    assert added.status_code == 201
    by_day = {d["date"]: len(d["slots"]) for d in before["days"]}
    assert by_day[day_off.isoformat()] == 3  # 08:00, 08:30, 09:00
    # Days 2+ are beyond the 12h notice regardless of the time the test runs.
    assert all(by_day[(local_today() + timedelta(days=i)).isoformat()] == 3 for i in range(2, 7))
    assert {d["date"]: len(d["slots"]) for d in after["days"]}[day_off.isoformat()] == 0

    exception_id = added.json()["exceptions"][0]["id"]
    assert (await partner.delete(f"/me/availability/exceptions/{exception_id}")).status_code == 204
    assert (await partner.delete(f"/me/availability/exceptions/{exception_id}")).status_code == 404


async def test_extra_hours_and_invalid_exceptions(make_client: MakeClient) -> None:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    await partner.put("/me/availability", json={"timezone": "America/Chicago", "windows": []})
    day = (local_today() + timedelta(days=4)).isoformat()

    extra = await partner.post(
        "/me/availability/exceptions",
        json={"date": day, "kind": "available", "start": "14:00", "end": "16:00"},
    )
    no_times = await partner.post(
        "/me/availability/exceptions", json={"date": day, "kind": "available"}
    )
    past = await partner.post(
        "/me/availability/exceptions",
        json={"date": (local_today() - timedelta(days=1)).isoformat(), "kind": "unavailable"},
    )
    preview = (await partner.get("/me/availability/preview", params={"days": 7})).json()

    assert extra.status_code == 201
    assert no_times.status_code == 422
    assert past.status_code == 422
    assert {d["date"]: len(d["slots"]) for d in preview["days"]}[day] == 3


# --- Search -----------------------------------------------------------------------------


async def test_search_filters_by_approval_level_schedule_and_distance(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    downtown, north = await club_ids(client, deliver)
    _, strong = await make_partner(make_client, [downtown], level=5.0)
    _, steady = await make_partner(make_client, [north], level=4.0)
    await make_partner(make_client, [downtown], approved=False)
    await make_partner(make_client, [downtown], schedule=None)

    near_downtown = {"lat": BASE_LAT, "lon": BASE_LON, "radius_km": 10}
    everyone = (await client.get("/partners/search", params=near_downtown)).json()
    advanced = (
        await client.get("/partners/search", params={**near_downtown, "min_level": 4.5})
    ).json()
    tight = (await client.get("/partners/search", params={**near_downtown, "radius_km": 1})).json()
    at_north_club = (
        await client.get("/partners/search", params={**near_downtown, "club_id": north})
    ).json()

    assert [p["user_id"] for p in everyone] == [strong, steady]  # nearest first
    assert everyone[0]["ntrp_rating"] == 5.0
    assert everyone[0]["clubs"][0]["name"] == "Austin Tennis Center"
    assert everyone[0]["next_slot"] is not None
    assert [p["user_id"] for p in advanced] == [strong]
    assert [p["user_id"] for p in tight] == [strong]
    assert [p["user_id"] for p in at_north_club] == [steady]


async def test_search_on_a_date_lists_that_days_slots(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    downtown, _ = await club_ids(client, deliver)
    _, morning = await make_partner(make_client, [downtown])
    _, weekends = await make_partner(
        make_client,
        [downtown],
        schedule=[{"weekday": 5, "start": "10:00", "end": "12:00"}],
    )
    day = local_today() + timedelta(days=3)
    while day.weekday() >= 5:  # pick a weekday
        day += timedelta(days=1)

    results = (
        await client.get(
            "/partners/search",
            params={"lat": BASE_LAT, "lon": BASE_LON, "date": day.isoformat(), "duration": 90},
        )
    ).json()

    assert [p["user_id"] for p in results] == [morning, weekends]  # bookable that day first
    local = [datetime.fromisoformat(s).astimezone(CHICAGO) for s in results[0]["slots"]]
    assert [t.strftime("%H:%M") for t in local] == ["08:00", "08:30"]  # 90 min fits twice
    assert results[1]["slots"] == []


async def test_search_validates_duration_and_requires_sign_in(
    make_client: MakeClient, api_client: AsyncClient
) -> None:
    client = await make_client("client")
    params = {"lat": BASE_LAT, "lon": BASE_LON}
    assert (
        await client.get("/partners/search", params={**params, "duration": 45})
    ).status_code == 422
    assert (await api_client.get("/partners/search", params=params)).status_code == 401


async def test_public_partner_page_and_slots(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    downtown, _ = await club_ids(client, deliver)
    _, approved = await make_partner(make_client, [downtown])
    _, pending = await make_partner(make_client, [downtown], approved=False)

    page = await client.get(f"/partners/{approved}")
    slots = await client.get(f"/partners/{approved}/slots", params={"days": 5})

    assert page.status_code == 200
    assert page.json()["clubs"][0]["name"] == "Austin Tennis Center"
    assert page.json()["ntrp_rating"] == 4.5
    assert slots.json()["timezone"] == "America/Chicago"
    assert len(slots.json()["days"]) == 5
    assert (await client.get(f"/partners/{pending}")).status_code == 404
    assert (await client.get(f"/partners/{pending}/slots")).status_code == 404


# --- Suggestions from the player's courts -----------------------------------------------


async def test_suggestions_come_from_the_players_courts(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    downtown, north = await club_ids(client, deliver)  # ~2.2 km apart
    _, at_my_court = await make_partner(make_client, [downtown], level=4.0)
    _, nearby = await make_partner(make_client, [north], level=5.0)
    await make_partner(make_client, [downtown], approved=False)

    nothing_saved = (await client.get("/partners/suggested")).json()
    await client.put("/me/clubs", json={"club_ids": [downtown]})
    within_5 = (await client.get("/partners/suggested")).json()
    same_court = (await client.get("/partners/suggested", params={"radius_km": 0})).json()
    advanced = (await client.get("/partners/suggested", params={"min_level": 4.5})).json()

    assert nothing_saved == []
    assert [p["user_id"] for p in within_5] == [at_my_court, nearby]  # same court first
    assert within_5[0]["clubs"][0] == {
        "id": downtown,
        "name": "Austin Tennis Center",
        "distance_km": 0.0,
        "near_court": "Austin Tennis Center",
    }
    assert within_5[1]["clubs"][0]["near_court"] == "Austin Tennis Center"
    assert within_5[1]["clubs"][0]["distance_km"] > 2
    assert [p["user_id"] for p in same_court] == [at_my_court]
    assert [p["user_id"] for p in advanced] == [nearby]


async def test_suggestions_rank_bookable_partners_first(
    make_client: MakeClient, geocoder, sources, deliver
) -> None:
    client = await make_client("client")
    downtown, north = await club_ids(client, deliver)
    _, weekends = await make_partner(
        make_client, [downtown], schedule=[{"weekday": 5, "start": "10:00", "end": "12:00"}]
    )
    _, mornings = await make_partner(make_client, [north])
    await client.put("/me/clubs", json={"club_ids": [downtown, north]})
    day = local_today() + timedelta(days=3)
    while day.weekday() >= 5:
        day += timedelta(days=1)

    results = (
        await client.get("/partners/suggested", params={"date": day.isoformat(), "radius_km": 0})
    ).json()

    assert [p["user_id"] for p in results] == [mornings, weekends]
    assert results[0]["clubs"][0]["near_court"] == "Tennis courts"
    assert results[1]["slots"] == []


async def test_only_players_get_suggestions(make_client: MakeClient) -> None:
    partner = await make_client("partner")
    client = await make_client("client")
    assert (await partner.get("/partners/suggested")).status_code == 403
    assert (await client.get("/partners/suggested", params={"radius_km": 30})).status_code == 422
