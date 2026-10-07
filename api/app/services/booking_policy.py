"""Booking rules as pure functions: who may do what to a booking, when, and what it costs.

Kept free of I/O so every rule is unit-tested directly. Thresholds come from settings
(free cancellation window, late fee share), matching the agency's published policies:
  - client cancels ≥ window before start → free; inside the window → late fee (50%)
  - partner cancels → client owes nothing
  - rain-out (admin) → client owes nothing and earns a rebooking credit
  - after the start time the partner records completed / no-show
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.models import BookingStatus


class Actor(StrEnum):
    CLIENT = "client"
    PARTNER = "partner"
    ADMIN = "admin"


class Action(StrEnum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    COMPLETE = "complete"
    NO_SHOW = "no_show"
    RAIN_OUT = "rain_out"


@dataclass(frozen=True)
class Policy:
    free_cancellation: timedelta
    late_fee_fraction: Decimal


@dataclass(frozen=True)
class CancellationOutcome:
    status: BookingStatus
    fee_fraction: Decimal


class PolicyError(Exception):
    pass


def is_hold_expired(status: BookingStatus, hold_expires_at: datetime | None, now: datetime) -> bool:
    return status is BookingStatus.HELD and hold_expires_at is not None and now >= hold_expires_at


def allowed_actions(
    *,
    status: BookingStatus,
    actor: Actor,
    starts_at: datetime,
    hold_expires_at: datetime | None,
    now: datetime,
) -> set[Action]:
    """What `actor` may do to the booking right now (drives both the API and the UI)."""
    started = now >= starts_at
    if status is BookingStatus.HELD:
        if is_hold_expired(status, hold_expires_at, now):
            return set()
        return {Action.CONFIRM, Action.CANCEL} if actor is Actor.CLIENT else set()
    if status is not BookingStatus.CONFIRMED:
        return set()
    if actor is Actor.CLIENT:
        return set() if started else {Action.CANCEL}
    if actor is Actor.PARTNER:
        return {Action.COMPLETE, Action.NO_SHOW} if started else {Action.CANCEL}
    return {Action.RAIN_OUT, Action.CANCEL}  # admin


def cancellation_outcome(
    *, status: BookingStatus, actor: Actor, starts_at: datetime, now: datetime, policy: Policy
) -> CancellationOutcome:
    if status is BookingStatus.HELD:
        # Releasing a hold before checkout costs nothing.
        return CancellationOutcome(BookingStatus.CANCELLED_FREE, Decimal(0))
    if actor is Actor.CLIENT:
        if now >= starts_at:
            raise PolicyError("Sessions can't be cancelled after they start")
        late = starts_at - now < policy.free_cancellation
        return (
            CancellationOutcome(BookingStatus.CANCELLED_LATE, policy.late_fee_fraction)
            if late
            else CancellationOutcome(BookingStatus.CANCELLED_FREE, Decimal(0))
        )
    # Partner or admin cancelling: never the client's fault.
    return CancellationOutcome(BookingStatus.PARTNER_CANCELLED, Decimal(0))


def free_cancellation_until(starts_at: datetime, policy: Policy) -> datetime:
    return starts_at - policy.free_cancellation


def transition(
    *,
    status: BookingStatus,
    action: Action,
    actor: Actor,
    starts_at: datetime,
    hold_expires_at: datetime | None,
    now: datetime,
) -> BookingStatus:
    """Target status for a non-cancel action, or PolicyError if it isn't allowed now."""
    allowed = allowed_actions(
        status=status, actor=actor, starts_at=starts_at, hold_expires_at=hold_expires_at, now=now
    )
    if action not in allowed:
        if is_hold_expired(status, hold_expires_at, now):
            raise PolicyError("This hold has expired — please choose the time again")
        raise PolicyError(f"Can't {action.value.replace('_', ' ')} this booking now")
    return {
        Action.CONFIRM: BookingStatus.CONFIRMED,
        Action.COMPLETE: BookingStatus.COMPLETED,
        Action.NO_SHOW: BookingStatus.NO_SHOW,
        Action.RAIN_OUT: BookingStatus.RAINED_OUT,
    }[action]
