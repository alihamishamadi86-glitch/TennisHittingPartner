from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.slots import (
    DateException,
    WeeklyWindow,
    day_windows,
    generate_slots,
    group_by_local_date,
    merge,
    subtract,
)

NY = ZoneInfo("America/New_York")
MADRID = ZoneInfo("Europe/Madrid")
HOUR = timedelta(hours=1)
LONG_AGO = datetime(2000, 1, 1, tzinfo=UTC)


def h(hours: float) -> int:
    return int(hours * 60)


def slots(
    weekly: list[WeeklyWindow],
    day: date,
    tz: ZoneInfo = NY,
    duration: timedelta = HOUR,
    exceptions: list[DateException] | None = None,
    now: datetime = LONG_AGO,
    min_notice: timedelta = timedelta(0),
    busy: list[tuple[datetime, datetime]] | None = None,
) -> list[str]:
    result = generate_slots(
        weekly=weekly,
        exceptions=exceptions or [],
        tz=tz,
        first_day=day,
        last_day=day,
        duration=duration,
        now=now,
        min_notice=min_notice,
        busy=busy or [],
    )
    return [s.astimezone(tz).strftime("%H:%M%z") for s in result]


# 2026-10-12 is a Monday.
MONDAY = date(2026, 10, 12)


def test_merge_and_subtract() -> None:
    assert merge([(60, 120), (100, 180), (200, 240)]) == [(60, 180), (200, 240)]
    assert merge([(60, 120), (120, 180)]) == [(60, 180)]
    assert subtract([(0, 600)], (120, 180)) == [(0, 120), (180, 600)]
    assert subtract([(0, 600)], (0, 600)) == []
    assert subtract([(100, 200)], (300, 400)) == [(100, 200)]


def test_weekly_window_is_cut_into_half_hour_starts() -> None:
    weekly = [WeeklyWindow(0, h(7), h(9))]
    assert slots(weekly, MONDAY) == ["07:00-0400", "07:30-0400", "08:00-0400"]
    assert slots(weekly, MONDAY, duration=timedelta(minutes=90)) == ["07:00-0400", "07:30-0400"]
    assert slots(weekly, MONDAY + timedelta(days=1)) == []  # Tuesday: no rules


def test_window_until_midnight() -> None:
    weekly = [WeeklyWindow(0, h(22), h(24))]
    assert slots(weekly, MONDAY) == ["22:00-0400", "22:30-0400", "23:00-0400"]


def test_overlapping_rules_are_merged() -> None:
    weekly = [WeeklyWindow(0, h(7), h(8)), WeeklyWindow(0, h(7.5), h(9))]
    assert slots(weekly, MONDAY) == ["07:00-0400", "07:30-0400", "08:00-0400"]


def test_day_off_and_blocked_hours() -> None:
    weekly = [WeeklyWindow(0, h(7), h(12))]
    off = DateException(MONDAY, available=False)
    dentist = DateException(MONDAY, available=False, start=h(9), end=h(10))

    assert day_windows(MONDAY, weekly, [off]) == []
    assert day_windows(MONDAY, weekly, [dentist]) == [(h(7), h(9)), (h(10), h(12))]
    assert "09:00-0400" not in slots(weekly, MONDAY, exceptions=[dentist])
    assert "08:00-0400" in slots(weekly, MONDAY, exceptions=[dentist])


def test_extra_hours_on_a_date() -> None:
    extra = DateException(MONDAY + timedelta(days=5), available=True, start=h(14), end=h(16))
    assert slots([], MONDAY + timedelta(days=5), exceptions=[extra]) == [
        "14:00-0400",
        "14:30-0400",
        "15:00-0400",
    ]


def test_minimum_notice() -> None:
    weekly = [WeeklyWindow(0, h(7), h(12))]
    now = datetime(2026, 10, 11, 21, 0, tzinfo=NY)  # Sunday 21:00
    assert slots(weekly, MONDAY, now=now, min_notice=timedelta(hours=12)) == [
        "09:00-0400",
        "09:30-0400",
        "10:00-0400",
        "10:30-0400",
        "11:00-0400",
    ]


def test_busy_periods_are_excluded() -> None:
    weekly = [WeeklyWindow(0, h(7), h(10))]
    booked = (
        datetime(2026, 10, 12, 8, 0, tzinfo=NY).astimezone(UTC),
        datetime(2026, 10, 12, 9, 0, tzinfo=NY).astimezone(UTC),
    )
    assert slots(weekly, MONDAY, busy=[booked]) == ["07:00-0400", "09:00-0400"]


def test_spring_forward_skips_the_missing_hour() -> None:
    # 2026-03-08: New York clocks jump 02:00 → 03:00.
    sunday = date(2026, 3, 8)
    weekly = [WeeklyWindow(6, h(1), h(5))]
    result = slots(weekly, sunday)
    assert result == ["01:00-0500", "01:30-0500", "03:00-0400", "03:30-0400", "04:00-0400"]
    assert not any(s.startswith("02:") for s in result)


def test_fall_back_repeated_hour_gives_two_real_slots() -> None:
    # 2026-11-01: New York clocks go 02:00 → 01:00; 01:00–02:00 happens twice.
    sunday = date(2026, 11, 1)
    weekly = [WeeklyWindow(6, h(0), h(3))]
    result = generate_slots(
        weekly=weekly,
        exceptions=[],
        tz=NY,
        first_day=sunday,
        last_day=sunday,
        duration=HOUR,
        now=LONG_AGO,
        min_notice=timedelta(0),
    )
    # 4 real hours in the window → 7 one-hour starts every 30 min, all distinct instants.
    assert len(result) == 7
    assert len(set(result)) == 7
    assert result[-1] - result[0] == timedelta(hours=3)


def test_europe_dst_and_utc_output() -> None:
    # 2026-03-29: Madrid jumps 02:00 → 03:00.
    sunday = date(2026, 3, 29)
    result = generate_slots(
        weekly=[WeeklyWindow(6, h(1), h(4))],
        exceptions=[],
        tz=MADRID,
        first_day=sunday,
        last_day=sunday,
        duration=HOUR,
        now=LONG_AGO,
        min_notice=timedelta(0),
    )
    assert all(s.tzinfo == UTC for s in result)
    # 2 real hours: 01:00, 01:30 (ends 03:30 after the jump), 03:00
    assert [s.astimezone(MADRID).strftime("%H:%M") for s in result] == ["01:00", "01:30", "03:00"]


def test_group_by_local_date() -> None:
    late = datetime(2026, 10, 13, 3, 30, tzinfo=UTC)  # 23:30 Monday in New York
    assert list(group_by_local_date([late], NY)) == [MONDAY]
