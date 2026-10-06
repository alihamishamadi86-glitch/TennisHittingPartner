import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://thp:thp@localhost:5432/thp_test")
os.environ.setdefault("PUSH_AUTH_ENABLED", "false")
os.environ.pop("PUBSUB_EMULATOR_HOST", None)

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import get_sessionmaker
from app.events.publisher import InMemoryPublisher

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
            text("TRUNCATE outbox_events, processed_events, system_pings RESTART IDENTITY")
        )
        await session.commit()


@pytest.fixture
def publisher(monkeypatch: pytest.MonkeyPatch) -> InMemoryPublisher:
    fake = InMemoryPublisher()
    monkeypatch.setattr("app.routers.system.get_publisher", lambda: fake)
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
