from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.integrations.email import InMemoryEmailSender
from app.integrations.storage import LocalStorage

MakeClient = Callable[..., Awaitable[AsyncClient]]

CLIENT_PROFILE = {
    "ntrp_rating": 3.5,
    "utr_rating": 4.25,
    "years_playing": 4,
    "dominant_hand": "right",
    "play_style": "baseliner",
    "city": "  Austin ",
    "region": "TX",
    "country_code": "US",
    "goals": ["rally", "match_play", "rally"],
}

PARTNER_PROFILE = {
    "ntrp_rating": 5.0,
    "years_playing": 15,
    "dominant_hand": "left",
    "play_style": "all_court",
    "city": "Austin",
    "region": "TX",
    "background": "college",
    "bio": "Former D1 college player. I love long baseline rallies and helping players groove "
    "their strokes with consistent, live-ball hitting.",
    "service_radius_km": 20,
}

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


async def upload_photo(client: AsyncClient, data: bytes = PNG, content_type: str = "image/png"):  # type: ignore[no-untyped-def]
    target = (
        await client.post(
            "/me/photo/upload-url", json={"content_type": content_type, "size": len(data)}
        )
    ).json()
    path = target["upload_url"].removeprefix("http://localhost:3000/api")
    put = await client.put(path, content=data, headers=target["headers"])
    assert put.status_code == 204, put.text
    return target["object_name"]


# --- Client profiles --------------------------------------------------------------------


async def test_client_profile_round_trip(make_client: MakeClient) -> None:
    client = await make_client("client")
    assert (await client.get("/me/client-profile")).status_code == 404
    assert (await client.get("/me")).json()["profile_complete"] is False

    saved = await client.put("/me/client-profile", json=CLIENT_PROFILE)

    assert saved.status_code == 200
    body = saved.json()
    assert body["ntrp_rating"] == 3.5
    assert body["utr_rating"] == 4.25
    assert body["city"] == "Austin"
    assert body["goals"] == ["rally", "match_play"]
    assert (await client.get("/me/client-profile")).json()["ntrp_rating"] == 3.5
    assert (await client.get("/me")).json()["profile_complete"] is True


async def test_profile_postal_code_is_normalized(make_client: MakeClient) -> None:
    client = await make_client("client")
    saved = await client.put(
        "/me/client-profile",
        json={**CLIENT_PROFILE, "country_code": "GB", "postal_code": " sw1a  1aa"},
    )
    assert saved.status_code == 200
    assert saved.json()["postal_code"] == "SW1A 1AA"


async def test_client_profile_can_be_updated(make_client: MakeClient) -> None:
    client = await make_client("client")
    await client.put("/me/client-profile", json=CLIENT_PROFILE)
    updated = await client.put("/me/client-profile", json={**CLIENT_PROFILE, "ntrp_rating": 4.0})
    assert updated.json()["ntrp_rating"] == 4.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"ntrp_rating": 4.3},
        {"ntrp_rating": 7.5},
        {"ntrp_rating": 1.0},
        {"utr_rating": 17},
        {"country_code": "usa"},
        {"city": ""},
        {"goals": ["world_domination"]},
    ],
)
async def test_client_profile_validation(make_client: MakeClient, overrides: dict) -> None:
    client = await make_client("client")
    response = await client.put("/me/client-profile", json={**CLIENT_PROFILE, **overrides})
    assert response.status_code == 422


async def test_profile_endpoints_enforce_role(make_client: MakeClient) -> None:
    client = await make_client("client")
    partner = await make_client("partner")
    assert (await partner.put("/me/client-profile", json=CLIENT_PROFILE)).status_code == 403
    assert (await client.put("/me/partner-profile", json=PARTNER_PROFILE)).status_code == 403


# --- Partner profiles & application -----------------------------------------------------


async def test_partner_draft_reports_missing_requirements(make_client: MakeClient) -> None:
    partner = await make_client("partner")
    draft = await partner.put(
        "/me/partner-profile", json={**PARTNER_PROFILE, "bio": "", "background": None}
    )

    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    assert set(draft.json()["missing_for_application"]) == {"photo", "bio", "background"}
    assert (await partner.get("/me")).json()["profile_complete"] is False

    submit = await partner.post("/me/partner-profile/submit")
    assert submit.status_code == 422
    assert set(submit.json()["detail"]["missing"]) == {"photo", "bio", "background"}


async def test_partner_below_minimum_level_cannot_apply(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json={**PARTNER_PROFILE, "ntrp_rating": 4.0})
    await partner.put("/me/photo", json={"object_name": await upload_photo(partner)})

    submit = await partner.post("/me/partner-profile/submit")
    assert submit.json()["detail"]["missing"] == ["ntrp_rating"]


async def test_partner_submits_application_and_admins_are_notified(
    make_client: MakeClient,
    storage: LocalStorage,
    deliver,
    email_sender: InMemoryEmailSender,
) -> None:
    await make_client("admin-to-be", email="admin@example.com", admin=True)
    partner = await make_client("partner", email="sam@example.com")
    await deliver()
    email_sender.outbox.clear()

    assert (await partner.post("/me/partner-profile/submit")).status_code == 404
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    await partner.put("/me/photo", json={"object_name": await upload_photo(partner)})

    submitted = await partner.post("/me/partner-profile/submit")

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "applied"
    assert submitted.json()["submitted_at"]
    assert (await partner.get("/me")).json()["profile_complete"] is True
    assert (await partner.post("/me/partner-profile/submit")).status_code == 409

    assert await deliver() == ["partner.application_submitted"]
    assert [m.to for m in email_sender.outbox] == ["admin@example.com"]
    assert "/admin/partners/" in email_sender.outbox[0].text
