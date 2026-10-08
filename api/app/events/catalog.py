"""Single source of truth for event types.

Each event type maps 1:1 to a Pub/Sub topic (optionally prefixed). The local emulator bootstrap
reads this list; keep `infra/terraform/pubsub.tf` (var.event_types) in sync when adding events.
"""

from app.core.config import get_settings

SYSTEM_PING = "system.ping"
USER_REGISTERED = "user.registered"
EMAIL_VERIFICATION_REQUESTED = "auth.email_verification_requested"
PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"  # noqa: S105 (event name)
PARTNER_APPLICATION_SUBMITTED = "partner.application_submitted"
PARTNER_VERIFICATION_DECIDED = "partner.verification_decided"
CLUBS_DISCOVERY_REQUESTED = "clubs.discovery.requested"
BOOKING_CONFIRMED = "booking.confirmed"
BOOKING_CANCELLED = "booking.cancelled"
BOOKING_COMPLETED = "booking.completed"
BOOKING_RAINED_OUT = "booking.rained_out"
PAYMENT_REFUND_REQUESTED = "payment.refund_requested"

EVENT_TYPES: tuple[str, ...] = (
    SYSTEM_PING,
    USER_REGISTERED,
    EMAIL_VERIFICATION_REQUESTED,
    PASSWORD_RESET_REQUESTED,
    PARTNER_APPLICATION_SUBMITTED,
    PARTNER_VERIFICATION_DECIDED,
    CLUBS_DISCOVERY_REQUESTED,
    BOOKING_CONFIRMED,
    BOOKING_CANCELLED,
    BOOKING_COMPLETED,
    BOOKING_RAINED_OUT,
    PAYMENT_REFUND_REQUESTED,
)


def topic_name(event_type: str) -> str:
    return f"{get_settings().pubsub_topic_prefix}{event_type}"
