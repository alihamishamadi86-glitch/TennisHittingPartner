from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.core.cookies import REFRESH_COOKIE
from app.integrations.google_oauth import GoogleIdentity, GoogleOAuthError, get_google_oauth

PASSWORD = "correct-horse-battery"
WEB = "http://localhost:3000"


class FakeGoogle:
    def __init__(self) -> None:
        self.identity = GoogleIdentity(
            subject="google-sub-1",
            email="pat@gmail.com",
            email_verified=True,
            name="Pat Google",
            picture="https://example.com/pat.png",
        )
        self.issued: dict[str, tuple[str, str]] = {}

    def authorization_url(self, state: str, nonce: str, code_verifier: str) -> str:
        self.issued[state] = (nonce, code_verifier)
        return f"https://accounts.example/auth?state={state}"

    async def exchange_code(self, code: str, code_verifier: str, nonce: str) -> GoogleIdentity:
        if (nonce, code_verifier) not in self.issued.values():
            raise GoogleOAuthError("verifier/nonce mismatch")
        return self.identity


@pytest.fixture
def google() -> Iterator[FakeGoogle]:
    from app.main import app

    fake = FakeGoogle()
    app.dependency_overrides[get_google_oauth] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_google_oauth, None)


async def google_sign_in(client: AsyncClient, **params: str) -> str:
    """Run login → callback; returns the final redirect location."""
    start = await client.get("/auth/google/login", params=params)
    assert start.status_code == 302
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    callback = await client.get("/auth/google/callback", params={"code": "c", "state": state})
    assert callback.status_code == 302
    return callback.headers["location"]


async def test_new_google_user_with_role_lands_on_next_path(
    api_client: AsyncClient, google: FakeGoogle, publisher
) -> None:
    location = await google_sign_in(api_client, role="partner", next="/partners/me")

    assert location == f"{WEB}/partners/me"
    me = (await api_client.get("/me")).json()
    assert me["email"] == "pat@gmail.com"
    assert me["role"] == "partner"
    assert me["email_verified"] is True
    assert me["has_password"] is False
    assert me["full_name"] == "Pat Google"


async def test_google_user_without_role_is_sent_to_onboarding(
    api_client: AsyncClient, google: FakeGoogle, publisher
) -> None:
    assert await google_sign_in(api_client) == f"{WEB}/onboarding/role"

    chosen = await api_client.put("/me/role", json={"role": "client"})
    again = await api_client.put("/me/role", json={"role": "partner"})

    assert chosen.status_code == 200
    assert chosen.json()["role"] == "client"
    assert again.status_code == 409


async def test_returning_google_user_signs_into_same_account(
    api_client: AsyncClient, google: FakeGoogle, publisher
) -> None:
    await google_sign_in(api_client, role="client")
    first_id = (await api_client.get("/me")).json()["id"]
    api_client.cookies.clear()

    await google_sign_in(api_client)
    assert (await api_client.get("/me")).json()["id"] == first_id


async def test_google_links_to_verified_password_account(
    api_client: AsyncClient, google: FakeGoogle, deliver, email_sender
) -> None:
    from tests.test_auth import register, token_from

    await register(api_client, email="pat@gmail.com")
    await deliver()
    await api_client.post(
        "/auth/verify-email", json={"token": token_from(email_sender.outbox[0].text)}
    )
    password_user = (await api_client.get("/me")).json()
    api_client.cookies.clear()

    await google_sign_in(api_client)
    me = (await api_client.get("/me")).json()
    assert me["id"] == password_user["id"]
    assert me["has_password"] is True


async def test_google_takes_over_unverified_squatted_account(
    api_client: AsyncClient, google: FakeGoogle, publisher
) -> None:
    """Pre-account-takeover: a squatter's password and sessions must not survive."""
    from tests.test_auth import register

    await register(api_client, email="pat@gmail.com")
    squatter_refresh = api_client.cookies.get(REFRESH_COOKIE)
    api_client.cookies.clear()

    await google_sign_in(api_client)
    me = (await api_client.get("/me")).json()
    assert me["has_password"] is False
    assert me["email_verified"] is True

    api_client.cookies.clear()
    api_client.cookies.set(REFRESH_COOKIE, squatter_refresh)
    assert (await api_client.post("/auth/refresh")).status_code == 401
    squatter_login = await api_client.post(
        "/auth/login", json={"email": "pat@gmail.com", "password": PASSWORD}
    )
    assert squatter_login.status_code == 401


async def test_state_mismatch_is_rejected(api_client: AsyncClient, google: FakeGoogle) -> None:
    await api_client.get("/auth/google/login")
    callback = await api_client.get(
        "/auth/google/callback", params={"code": "c", "state": "forged"}
    )
    assert callback.headers["location"] == f"{WEB}/login?error=google"
    assert (await api_client.get("/me")).status_code == 401


async def test_unverified_google_email_is_rejected(
    api_client: AsyncClient, google: FakeGoogle
) -> None:
    google.identity = GoogleIdentity("sub-2", "x@gmail.com", False, "X", None)
    assert await google_sign_in(api_client) == f"{WEB}/login?error=google"


@pytest.mark.parametrize("evil", ["//evil.example", "https://evil.example", "/\\evil.example"])
async def test_open_redirects_are_ignored(
    api_client: AsyncClient, google: FakeGoogle, publisher, evil: str
) -> None:
    assert await google_sign_in(api_client, role="client", next=evil) == f"{WEB}/dashboard"
