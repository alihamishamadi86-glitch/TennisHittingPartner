import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://thp:thp@localhost:5432/thp_test")
os.environ.setdefault("PUSH_AUTH_ENABLED", "false")
# Tests call the API directly (not through the Next.js /api proxy), so scope cookies to /auth.
os.environ["AUTH_COOKIE_PATH"] = "/auth"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
os.environ["EMAIL_BACKEND"] = "console"
os.environ.pop("PUBSUB_EMULATOR_HOST", None)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.events.envelope import EventEnvelope
from app.events.publisher import InMemoryPublisher
from app.events.registry import dispatch
from app.integrations.email import InMemoryEmailSender

if TYPE_CHECKING:
    from app.integrations.storage import LocalStorage

API_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        check=True,
        env=os.environ,
    )


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with get_sessionmaker()() as session:
        await session.execute(
            text(
                "TRUNCATE outbox_events, processed_events, system_pings, users, auth_identities,"
                " refresh_tokens, email_tokens, client_profiles, partner_profiles,"
                " partner_verifications RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture(autouse=True)
def publisher(monkeypatch: pytest.MonkeyPatch) -> InMemoryPublisher:
    """Every test publishes in memory; tests must never reach real Pub/Sub."""
    fake = InMemoryPublisher()
    monkeypatch.setattr("app.events.outbox.get_publisher", lambda: fake)
    return fake


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        yield client


@pytest.fixture
async def worker_client() -> AsyncIterator[AsyncClient]:
    from app.worker import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://worker") as client:
        yield client


@pytest.fixture
def email_sender(monkeypatch: pytest.MonkeyPatch) -> InMemoryEmailSender:
    fake = InMemoryEmailSender()
    for module in ("auth", "partners"):
        monkeypatch.setattr(f"app.events.handlers.{module}.get_email_sender", lambda: fake)
    return fake


@pytest.fixture
def deliver(publisher: InMemoryPublisher):  # type: ignore[no-untyped-def]
    """Drain published messages through the worker's dispatcher, like Pub/Sub push would."""
    import app.events.handlers  # noqa: F401  (registers handlers)

    async def _deliver() -> list[str]:
        delivered = []
        while publisher.messages:
            _, data, _ = publisher.messages.pop(0)
            envelope = EventEnvelope.model_validate_json(data)
            await dispatch(get_sessionmaker(), envelope)
            delivered.append(envelope.type)
        return delivered

    return _deliver


@pytest.fixture
def storage(tmp_path: Path) -> Iterator["LocalStorage"]:
    from app.integrations.storage import LocalStorage, get_storage
    from app.main import app

    local = LocalStorage(str(tmp_path / "media"), "http://localhost:3000/api")
    app.dependency_overrides[get_storage] = lambda: local
    yield local
    app.dependency_overrides.pop(get_storage, None)


PASSWORD = "correct-horse-battery"


@pytest.fixture
async def make_client() -> AsyncIterator[Callable[..., Awaitable[AsyncClient]]]:
    """Factory for independent signed-in API clients: `await make_client(role="partner")`."""
    from app.main import app

    clients: list[AsyncClient] = []

    async def _make(role: str = "client", email: str | None = None, admin: bool = False):  # type: ignore[no-untyped-def]
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://api")
        clients.append(client)
        email = email or f"{role}-{len(clients)}@example.com"
        response = await client.post(
            "/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "full_name": f"{role.title()} User",
                "role": "client" if admin else role,
            },
        )
        assert response.status_code == 201, response.text
        if admin:
            from app.services.profiles import promote_to_admin

            async with get_sessionmaker()() as session:
                await promote_to_admin(session, email)
                await session.commit()
        return client

    yield _make
    for client in clients:
        await client.aclose()
