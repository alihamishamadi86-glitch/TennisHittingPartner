from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.db import get_sessionmaker
from app.integrations.email import InMemoryEmailSender
from app.integrations.storage import LocalStorage
from app.services.profiles import ProfileNotFoundError, promote_to_admin
from tests.test_profiles import PARTNER_PROFILE, upload_photo

MakeClient = Callable[..., Awaitable[AsyncClient]]


async def applied_partner(make_client: MakeClient) -> tuple[AsyncClient, str]:
    partner = await make_client("partner")
    await partner.put("/me/partner-profile", json=PARTNER_PROFILE)
    await partner.put("/me/photo", json={"object_name": await upload_photo(partner)})
    assert (await partner.post("/me/partner-profile/submit")).status_code == 200
    return partner, (await partner.get("/me")).json()["id"]


async def test_admin_endpoints_require_admin(make_client: MakeClient) -> None:
    client = await make_client("client")
    partner = await make_client("partner")
    assert (await client.get("/admin/partners")).status_code == 403
    assert (await partner.get("/admin/partners")).status_code == 403


async def test_queue_lists_submitted_partners_only(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    admin = await make_client("admin", admin=True)
    drafter = await make_client("partner")
    await drafter.put("/me/partner-profile", json=PARTNER_PROFILE)
    _, partner_id = await applied_partner(make_client)

    queue = (await admin.get("/admin/partners")).json()
    applied = (await admin.get("/admin/partners", params={"status": "applied"})).json()
    approved = (await admin.get("/admin/partners", params={"status": "approved"})).json()

    assert [p["user_id"] for p in queue] == [partner_id]
    assert [p["user_id"] for p in applied] == [partner_id]
    assert approved == []
    assert queue[0]["ntrp_rating"] == 5.0


async def test_screen_then_approve_records_history_and_emails_partner(
    make_client: MakeClient,
    storage: LocalStorage,
    deliver,
    email_sender: InMemoryEmailSender,
) -> None:
    admin = await make_client("admin", admin=True)
    partner, partner_id = await applied_partner(make_client)
    await deliver()
    email_sender.outbox.clear()

    screened = await admin.post(
        f"/admin/partners/{partner_id}/decision",
        json={"decision": "screened", "note": "Great consistency"},
    )
    missing_level = await admin.post(
        f"/admin/partners/{partner_id}/decision", json={"decision": "approved"}
    )
    approved = await admin.post(
        f"/admin/partners/{partner_id}/decision",
        json={"decision": "approved", "verified_ntrp_rating": 4.5},
    )

    assert screened.status_code == 200
    assert missing_level.status_code == 422
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "approved"
    assert body["verified_ntrp_rating"] == 4.5
    assert [(h["from_status"], h["to_status"]) for h in body["history"]] == [
        ("draft", "applied"),
        ("applied", "screened"),
        ("screened", "approved"),
    ]
    assert body["history"][1]["note"] == "Great consistency"

    profile = (await partner.get("/me/partner-profile")).json()
    assert profile["status"] == "approved"
    assert profile["approved_at"]

    assert await deliver() == ["partner.verification_decided", "partner.verification_decided"]
    subjects = [m.subject for m in email_sender.outbox]
    assert subjects == ["You passed your court screening", "You're approved as a hitting partner"]


async def test_invalid_transitions_are_rejected(
    make_client: MakeClient, storage: LocalStorage
) -> None:
    admin = await make_client("admin", admin=True)
    _, partner_id = await applied_partner(make_client)
    await admin.post(
        f"/admin/partners/{partner_id}/decision",
        json={"decision": "approved", "verified_ntrp_rating": 5.0},
    )

    response = await admin.post(
        f"/admin/partners/{partner_id}/decision", json={"decision": "screened"}
    )
    assert response.status_code == 409


async def test_rejected_partner_can_resubmit(
    make_client: MakeClient, storage: LocalStorage, deliver, email_sender: InMemoryEmailSender
) -> None:
    admin = await make_client("admin", admin=True)
    partner, partner_id = await applied_partner(make_client)
    await admin.post(
        f"/admin/partners/{partner_id}/decision",
        json={"decision": "rejected", "note": "Please add a clearer photo"},
    )
    await deliver()
    assert "Please add a clearer photo" in email_sender.outbox[-1].text

    resubmitted = await partner.post("/me/partner-profile/submit")
    assert resubmitted.status_code == 200
    assert resubmitted.json()["status"] == "applied"


async def test_unknown_partner_returns_404(make_client: MakeClient) -> None:
    admin = await make_client("admin", admin=True)
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await admin.get(f"/admin/partners/{missing}")).status_code == 404


async def test_promote_to_admin_requires_existing_account() -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(ProfileNotFoundError):
            await promote_to_admin(session, "nobody@example.com")
