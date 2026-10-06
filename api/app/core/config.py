from enum import StrEnum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.LOCAL
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://thp:thp@localhost:5432/thp"
    database_pool_size: int = 5

    # Pub/Sub. Locally the client library talks to the emulator when PUBSUB_EMULATOR_HOST is set.
    gcp_project_id: str = "thp-local"
    pubsub_topic_prefix: str = ""

    # Verification of OIDC tokens on push requests (Pub/Sub push, Cloud Scheduler, Cloud Tasks).
    # Disabled locally because the emulator does not sign requests.
    push_auth_enabled: bool = False
    push_auth_audience: str = ""
    push_auth_allowed_emails: list[str] = Field(default_factory=list)

    # Worker runs the outbox relay in-process every N seconds when > 0 (local dev only;
    # in GCP Cloud Scheduler calls POST /tasks/outbox-relay instead).
    outbox_relay_interval_seconds: float = 0
    outbox_relay_batch_size: int = 100

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Exposes POST /system/ping for end-to-end event pipeline checks.
    enable_system_ping: bool = True

    @property
    def is_cloud(self) -> bool:
        return self.environment in (Environment.STAGING, Environment.PRODUCTION)


@lru_cache
def get_settings() -> Settings:
    return Settings()
