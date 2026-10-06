"""Single source of truth for event types.

Each event type maps 1:1 to a Pub/Sub topic (optionally prefixed). The local emulator bootstrap
reads this list; keep `infra/terraform/pubsub.tf` (var.event_types) in sync when adding events.
"""

from app.core.config import get_settings

SYSTEM_PING = "system.ping"
USER_REGISTERED = "user.registered"
EMAIL_VERIFICATION_REQUESTED = "auth.email_verification_requested"
PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"  # noqa: S105 (event name)

EVENT_TYPES: tuple[str, ...] = (
    SYSTEM_PING,
    USER_REGISTERED,
    EMAIL_VERIFICATION_REQUESTED,
    PASSWORD_RESET_REQUESTED,
)


def topic_name(event_type: str) -> str:
    return f"{get_settings().pubsub_topic_prefix}{event_type}"
