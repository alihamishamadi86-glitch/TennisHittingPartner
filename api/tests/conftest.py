import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

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
                " refresh_tokens, email_tokens RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()


@pytest.fixture
def publisher(monkeypatch: pytest.MonkeyPatch) -> InMemoryPublisher:
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
    monkeypatch.setattr("app.events.handlers.auth.get_email_sender", lambda: fake)
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
