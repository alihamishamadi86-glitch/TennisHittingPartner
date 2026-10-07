from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models import BookingStatus
from app.services.booking_policy import (
    Action,
    Actor,
    Policy,
    PolicyError,
    allowed_actions,
    cancellation_outcome,
    transition,
)

POLICY = Policy(free_cancellation=timedelta(hours=12), late_fee_fraction=Decimal("0.5"))
START = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def actions(status: BookingStatus, actor: Actor, now: datetime, hold: datetime | None = None):  # type: ignore[no-untyped-def]
    return allowed_actions(
        status=status, actor=actor, starts_at=START, hold_expires_at=hold, now=now
    )


def test_client_can_confirm_or_release_a_live_hold() -> None:
    now = START - timedelta(days=2)
    hold = now + timedelta(minutes=10)
    assert actions(BookingStatus.HELD, Actor.CLIENT, now, hold) == {Action.CONFIRM, Action.CANCEL}
    assert actions(BookingStatus.HELD, Actor.PARTNER, now, hold) == set()
    assert actions(BookingStatus.HELD, Actor.CLIENT, hold, hold) == set()  # expired


def test_confirmed_booking_actions_before_and_after_start() -> None:
    before, after = START - timedelta(hours=1), START + timedelta(minutes=5)
    assert actions(BookingStatus.CONFIRMED, Actor.CLIENT, before) == {Action.CANCEL}
    assert actions(BookingStatus.CONFIRMED, Actor.CLIENT, after) == set()
    assert actions(BookingStatus.CONFIRMED, Actor.PARTNER, before) == {Action.CANCEL}
    assert actions(BookingStatus.CONFIRMED, Actor.PARTNER, after) == {
        Action.COMPLETE,
        Action.NO_SHOW,
    }
    assert Action.RAIN_OUT in actions(BookingStatus.CONFIRMED, Actor.ADMIN, after)


@pytest.mark.parametrize(
    "status",
    [s for s in BookingStatus if s not in (BookingStatus.HELD, BookingStatus.CONFIRMED)],
)
def test_finished_bookings_are_final(status: BookingStatus) -> None:
    for actor in Actor:
        assert actions(status, actor, START - timedelta(days=1)) == set()


@pytest.mark.parametrize(
    ("hours_before", "status", "fee"),
    [
        (48, BookingStatus.CANCELLED_FREE, Decimal(0)),
        (12, BookingStatus.CANCELLED_FREE, Decimal(0)),  # exactly at the window: free
        (11.99, BookingStatus.CANCELLED_LATE, Decimal("0.5")),
        (1, BookingStatus.CANCELLED_LATE, Decimal("0.5")),
    ],
)
def test_client_cancellation_window(
    hours_before: float, status: BookingStatus, fee: Decimal
) -> None:
    outcome = cancellation_outcome(
        status=BookingStatus.CONFIRMED,
        actor=Actor.CLIENT,
        starts_at=START,
        now=START - timedelta(hours=hours_before),
        policy=POLICY,
    )
    assert (outcome.status, outcome.fee_fraction) == (status, fee)


def test_client_cannot_cancel_after_start() -> None:
    with pytest.raises(PolicyError):
        cancellation_outcome(
            status=BookingStatus.CONFIRMED,
            actor=Actor.CLIENT,
            starts_at=START,
            now=START,
            policy=POLICY,
        )


def test_partner_cancellation_is_free_for_the_client() -> None:
    outcome = cancellation_outcome(
        status=BookingStatus.CONFIRMED,
        actor=Actor.PARTNER,
        starts_at=START,
        now=START - timedelta(hours=1),
        policy=POLICY,
    )
    assert (outcome.status, outcome.fee_fraction) == (BookingStatus.PARTNER_CANCELLED, 0)


def test_releasing_a_hold_is_free() -> None:
    outcome = cancellation_outcome(
        status=BookingStatus.HELD,
        actor=Actor.CLIENT,
        starts_at=START,
        now=START - timedelta(hours=1),
        policy=POLICY,
    )
    assert outcome == cancellation_outcome(
        status=BookingStatus.HELD,
        actor=Actor.CLIENT,
        starts_at=START,
        now=START - timedelta(days=5),
        policy=POLICY,
    )
    assert outcome.status is BookingStatus.CANCELLED_FREE


def test_transitions_and_errors() -> None:
    now = START - timedelta(days=1)
    hold = now + timedelta(minutes=10)
    assert (
        transition(
            status=BookingStatus.HELD,
            action=Action.CONFIRM,
            actor=Actor.CLIENT,
            starts_at=START,
            hold_expires_at=hold,
            now=now,
        )
        is BookingStatus.CONFIRMED
    )
    with pytest.raises(PolicyError, match="expired"):
        transition(
            status=BookingStatus.HELD,
            action=Action.CONFIRM,
            actor=Actor.CLIENT,
            starts_at=START,
            hold_expires_at=hold,
            now=hold,
        )
    with pytest.raises(PolicyError, match="complete"):
        transition(
            status=BookingStatus.CONFIRMED,
            action=Action.COMPLETE,
            actor=Actor.PARTNER,
            starts_at=START,
            hold_expires_at=None,
            now=now,  # before start
        )
