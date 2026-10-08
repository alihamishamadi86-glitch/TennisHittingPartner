from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
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

    database_url: str = "postgresql+asyncpg://thp:thp@localhost:55432/thp"
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

    # Public origin of the Next.js app. Browser traffic reaches the API through its /api proxy,
    # so links in emails and the OAuth redirect URI are built from this.
    public_web_url: str = "http://localhost:3000"

    # Auth
    jwt_secret: SecretStr = SecretStr("local-dev-only-insecure-jwt-secret-change-me")
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    email_verification_ttl_hours: int = 24
    password_reset_ttl_minutes: int = 60
    max_failed_logins: int = 5
    login_lockout_minutes: int = 15
    cookie_secure: bool = False
    # Browser-facing path of the API's /auth routes (behind the Next.js /api proxy). Refresh and
    # OAuth-state cookies are scoped to it so they are not sent on every request.
    auth_cookie_path: str = "/api/auth"

    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")

    # Email: "console" logs messages (staging until M7), "smtp" sends (Mailpit locally).
    email_backend: str = "console"
    email_from: str = "Tennis Hitting Partner <no-reply@tennishittingpartner.local>"
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    # File storage: "local" (dev; files on disk, served by the API) or "gcs".
    storage_backend: str = "local"
    local_storage_dir: str = ".media"
    gcs_bucket: str = ""
    max_photo_bytes: int = 5 * 1024 * 1024

    # Club discovery. Geoapify (OSM-based, free tier) when a key is set; otherwise the free
    # OSM services (Nominatim geocoding). Overpass is always the primary court source.
    geoapify_api_key: SecretStr = SecretStr("")
    # Public Overpass instances are often overloaded; they're tried in order. Point this at a
    # self-hosted instance for production volume.
    overpass_urls: list[str] = Field(
        default_factory=lambda: [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        ]
    )
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Identifies us to OSM services, as their usage policies require.
    geo_user_agent: str = "TennisHittingPartner/0.1 (+https://github.com/tennis-hitting-partner)"
    # Optional: finds websites for clubs OpenStreetMap/Wikidata don't know (free tier available).
    brave_search_api_key: SecretStr = SecretStr("")
    club_enrichment_refresh_days: int = 90
    city_search_radius_km: float = 20.0
    city_refresh_days: int = 30
    discovery_max_attempts: int = 5

    # Booking rules shared by availability (M4) and booking (M5).
    session_durations_minutes: list[int] = Field(default_factory=lambda: [60, 90])
    slot_step_minutes: int = 30
    min_booking_notice_hours: int = 12
    booking_horizon_days: int = 30
    hold_minutes: int = 10
    travel_buffer_minutes: int = 30
    free_cancellation_hours: int = 12
    late_cancellation_fee_fraction: float = 0.5

    # Prices in minor units per session length (minutes), and what the partner earns.
    currency: str = "usd"
    session_prices_cents: dict[int, int] = Field(default_factory=lambda: {60: 4500, 90: 6500})
    partner_pay_cents: dict[int, int] = Field(default_factory=lambda: {60: 3000, 90: 4500})
    rain_credit_days: int = 30

    # Payments: "stripe" in the cloud; "fake" simulates payments for local dev and tests.
    payment_provider: str = "fake"
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_publishable_key: str = ""
    stripe_webhook_secret: SecretStr = SecretStr("")

    # Minimum self-rated NTRP to apply as a hitting partner.
    min_partner_ntrp: float = 4.5

    @model_validator(mode="after")
    def _require_real_secrets_in_cloud(self) -> "Settings":
        if self.is_cloud and self.jwt_secret.get_secret_value().startswith("local-dev-only"):
            raise ValueError("JWT_SECRET must be set in staging/production")
        if self.environment is Environment.PRODUCTION and self.payment_provider != "stripe":
            raise ValueError("Production must use PAYMENT_PROVIDER=stripe")
        if self.payment_provider == "stripe" and not (
            self.stripe_secret_key.get_secret_value().strip() and self.stripe_publishable_key
        ):
            raise ValueError(
                "PAYMENT_PROVIDER=stripe needs STRIPE_SECRET_KEY and the publishable key"
            )
        return self

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.public_web_url}{self.auth_cookie_path}/google/callback"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret.get_secret_value())

    @property
    def is_cloud(self) -> bool:
        return self.environment in (Environment.STAGING, Environment.PRODUCTION)


@lru_cache
def get_settings() -> Settings:
    return Settings()
