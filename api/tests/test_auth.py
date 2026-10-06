import re
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.cookies import ACCESS_COOKIE, REFRESH_COOKIE
from app.core.db import get_sessionmaker
from app.core.security import hash_token
from app.events.publisher import InMemoryPublisher
from app.integrations.email import InMemoryEmailSender
from app.models import RefreshToken

PASSWORD = "correct-horse-battery"


async def register(client: AsyncClient, email: str = "pat@example.com", role: str = "client"):  # type: ignore[no-untyped-def]
    return await client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "full_name": "Pat Player", "role": role},
    )


def token_from(email_text: str) -> str:
    match = re.search(r"token=([\w-]+)", email_text)
    assert match, email_text
    return match.group(1)


async def test_providers_reports_google_availability(api_client: AsyncClient) -> None:
    assert (await api_client.get("/auth/providers")).json() == {"password": True, "google": True}


# --- Registration ----------------------------------------------------------------------


async def test_register_logs_in_and_returns_profile(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    response = await register(api_client, email="Pat@Example.com", role="partner")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "pat@example.com"
    assert body["role"] == "partner"
    assert body["email_verified"] is False
    assert body["has_password"] is True
    assert api_client.cookies.get(ACCESS_COOKIE)
    assert api_client.cookies.get(REFRESH_COOKIE)

    me = await api_client.get("/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["id"]


async def test_register_rejects_duplicate_email(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    api_client.cookies.clear()
    assert (await register(api_client, email="PAT@example.com")).status_code == 409


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "short"},
        {"role": "admin"},
        {"email": "not-an-email"},
        {"password": "pat@example.com", "email": "pat@example.com"},
    ],
)
async def test_register_validates_input(api_client: AsyncClient, overrides: dict[str, str]) -> None:
    payload = {
        "email": "pat@example.com",
        "password": PASSWORD,
        "full_name": "Pat",
        "role": "client",
    }
    response = await api_client.post("/auth/register", json={**payload, **overrides})
    assert response.status_code == 422


async def test_me_requires_authentication(api_client: AsyncClient) -> None:
    assert (await api_client.get("/me")).status_code == 401


# --- Login & lockout --------------------------------------------------------------------


async def test_login_with_valid_and_invalid_credentials(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    api_client.cookies.clear()

    bad = await api_client.post("/auth/login", json={"email": "pat@example.com", "password": "x"})
    unknown = await api_client.post(
        "/auth/login", json={"email": "no@example.com", "password": "x"}
    )
    good = await api_client.post(
        "/auth/login", json={"email": "PAT@example.com", "password": PASSWORD}
    )

    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()  # no account enumeration
    assert good.status_code == 200
    assert api_client.cookies.get(ACCESS_COOKIE)


async def test_account_locks_after_repeated_failures(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    api_client.cookies.clear()
    for _ in range(5):
        await api_client.post("/auth/login", json={"email": "pat@example.com", "password": "nope"})

    locked = await api_client.post(
        "/auth/login", json={"email": "pat@example.com", "password": PASSWORD}
    )
    assert locked.status_code == 429


# --- Refresh rotation -------------------------------------------------------------------


async def test_refresh_rotates_tokens(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    old_refresh = api_client.cookies.get(REFRESH_COOKIE)

    response = await api_client.post("/auth/refresh")

    assert response.status_code == 200
    new_refresh = api_client.cookies.get(REFRESH_COOKIE)
    assert new_refresh and new_refresh != old_refresh


async def test_concurrent_refresh_within_grace_does_not_revoke_session(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    old_refresh = api_client.cookies.get(REFRESH_COOKIE)
    await api_client.post("/auth/refresh")
    new_refresh = api_client.cookies.get(REFRESH_COOKIE)

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, old_refresh)
    assert (await api_client.post("/auth/refresh")).status_code == 401

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, new_refresh)
    assert (await api_client.post("/auth/refresh")).status_code == 200


async def test_reused_refresh_token_revokes_whole_family(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    stolen = api_client.cookies.get(REFRESH_COOKIE)
    await api_client.post("/auth/refresh")
    current = api_client.cookies.get(REFRESH_COOKIE)
    async with get_sessionmaker()() as session:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(stolen))
            .values(revoked_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await session.commit()

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, stolen)
    assert (await api_client.post("/auth/refresh")).status_code == 401

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, current)
    assert (await api_client.post("/auth/refresh")).status_code == 401


async def test_failed_refresh_clears_both_session_cookies(api_client: AsyncClient) -> None:
    api_client.cookies.set(REFRESH_COOKIE, "bogus-token-value")
    response = await api_client.post("/auth/refresh")

    assert response.status_code == 401
    cleared = response.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=") for c in cleared)
    assert any(c.startswith(f"{REFRESH_COOKIE}=") for c in cleared)


async def test_session_renew_redirects_back_with_fresh_cookies(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    old_refresh = api_client.cookies.get(REFRESH_COOKIE)
    api_client.cookies.delete(ACCESS_COOKIE)

    response = await api_client.get("/auth/session/renew", params={"next": "/bookings?x=1"})

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/bookings?x=1"
    assert api_client.cookies.get(ACCESS_COOKIE)
    assert api_client.cookies.get(REFRESH_COOKIE) != old_refresh


@pytest.mark.parametrize("refresh", [None, "bogus-token-value"])
async def test_session_renew_without_valid_session_goes_to_login(
    api_client: AsyncClient, refresh: str | None
) -> None:
    if refresh:
        api_client.cookies.set(REFRESH_COOKIE, refresh)
    response = await api_client.get("/auth/session/renew", params={"next": "//evil.example"})

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:3000/login?next=%2Fdashboard"


async def test_logout_revokes_session(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    await register(api_client)
    refresh = api_client.cookies.get(REFRESH_COOKIE)

    assert (await api_client.post("/auth/logout")).status_code == 204

    api_client.cookies.set(REFRESH_COOKIE, refresh)
    assert (await api_client.post("/auth/refresh")).status_code == 401


# --- Email verification -----------------------------------------------------------------


async def test_email_verification_flow(
    api_client: AsyncClient, deliver, email_sender: InMemoryEmailSender
) -> None:
    await register(api_client)
    assert await deliver() == ["user.registered"]
    assert len(email_sender.outbox) == 1
    token = token_from(email_sender.outbox[0].text)
    assert "/verify-email?token=" in email_sender.outbox[0].text

    verified = await api_client.post("/auth/verify-email", json={"token": token})
    reused = await api_client.post("/auth/verify-email", json={"token": token})

    assert verified.status_code == 200
    assert verified.json()["email_verified"] is True
    assert reused.status_code == 400


async def test_raw_email_tokens_never_enter_the_outbox(
    api_client: AsyncClient,
    deliver,
    email_sender: InMemoryEmailSender,
    publisher: InMemoryPublisher,
) -> None:
    await register(api_client)
    published = [data for _, data, _ in publisher.messages]
    await deliver()
    token = token_from(email_sender.outbox[0].text)
    assert all(token.encode() not in data for data in published)


async def test_verification_resend_has_cooldown(
    api_client: AsyncClient,
    deliver,
    email_sender: InMemoryEmailSender,
    publisher: InMemoryPublisher,
) -> None:
    await register(api_client)
    await deliver()

    assert (await api_client.post("/auth/verify-email/resend")).status_code == 202
    assert publisher.messages == []


# --- Password reset ---------------------------------------------------------------------


async def test_forgot_password_does_not_reveal_unknown_emails(
    api_client: AsyncClient, publisher: InMemoryPublisher
) -> None:
    response = await api_client.post("/auth/forgot-password", json={"email": "ghost@example.com"})
    assert response.status_code == 202
    assert publisher.messages == []


async def test_password_reset_flow_revokes_existing_sessions(
    api_client: AsyncClient, deliver, email_sender: InMemoryEmailSender
) -> None:
    await register(api_client)
    old_refresh = api_client.cookies.get(REFRESH_COOKIE)
    await deliver()
    email_sender.outbox.clear()

    await api_client.post("/auth/forgot-password", json={"email": "pat@example.com"})
    assert await deliver() == ["auth.password_reset_requested"]
    token = token_from(email_sender.outbox[0].text)
    new_password = "a-brand-new-password"

    reset = await api_client.post(
        "/auth/reset-password", json={"token": token, "password": new_password}
    )
    assert reset.status_code == 204

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, old_refresh)
    assert (await api_client.post("/auth/refresh")).status_code == 401

    api_client.cookies.clear()
    old_login = await api_client.post(
        "/auth/login", json={"email": "pat@example.com", "password": PASSWORD}
    )
    new_login = await api_client.post(
        "/auth/login", json={"email": "pat@example.com", "password": new_password}
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert new_login.json()["email_verified"] is True


# --- Origin check -----------------------------------------------------------------------


async def test_cross_site_state_changing_requests_are_rejected(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/auth/login",
        json={"email": "pat@example.com", "password": PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403


async def test_requests_from_our_web_origin_are_allowed(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/auth/login",
        json={"email": "pat@example.com", "password": PASSWORD},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code == 401
