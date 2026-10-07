"""Bookable slot generation. Pure functions: no I/O, fully deterministic, unit-tested.

Partners describe availability in local wall-clock time (weekly windows + date exceptions).
Each day's windows are converted to UTC *before* slots are cut, so DST transitions are
handled by construction: on spring-forward days the missing hour simply yields no slots, and
on fall-back days the repeated hour yields two distinct real slots.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Interval = tuple[int, int]  # minutes after local midnight, [start, end)


@dataclass(frozen=True)
class WeeklyWindow:
    weekday: int  # 0 = Monday
    start: int
    end: int


@dataclass(frozen=True)
class DateException:
    day: date
    available: bool  # True = extra hours, False = blocked
    start: int | None = None  # None/None = whole day (blocked only)
    end: int | None = None


def merge(intervals: Iterable[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract(intervals: Sequence[Interval], cut: Interval) -> list[Interval]:
    result: list[Interval] = []
    for start, end in intervals:
        if cut[1] <= start or cut[0] >= end:
            result.append((start, end))
            continue
        if start < cut[0]:
            result.append((start, cut[0]))
        if cut[1] < end:
            result.append((cut[1], end))
    return result


def day_windows(
    day: date, weekly: Sequence[WeeklyWindow], exceptions: Sequence[DateException]
) -> list[Interval]:
    """Local availability for one date: weekly rules, plus extra hours, minus blocks."""
    windows = merge((w.start, w.end) for w in weekly if w.weekday == day.weekday())
    todays = [e for e in exceptions if e.day == day]
    extra = [
        (e.start, e.end)
        for e in todays
        if e.available and e.start is not None and e.end is not None
    ]
    windows = merge([*windows, *extra])
    for exc in todays:
        if exc.available:
            continue
        if exc.start is None or exc.end is None:
            return []
        windows = subtract(windows, (exc.start, exc.end))
    return windows


def local_to_utc(day: date, minute: int, tz: ZoneInfo) -> datetime:
    naive = datetime.combine(day, time()) + timedelta(minutes=minute)
    return naive.replace(tzinfo=tz).astimezone(UTC)


def _overlaps(start: datetime, end: datetime, busy: Sequence[tuple[datetime, datetime]]) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in busy)


def generate_slots(
    *,
    weekly: Sequence[WeeklyWindow],
    exceptions: Sequence[DateException],
    tz: ZoneInfo,
    first_day: date,
    last_day: date,
    duration: timedelta,
    now: datetime,
    min_notice: timedelta,
    step: timedelta = timedelta(minutes=30),
    busy: Sequence[tuple[datetime, datetime]] = (),
) -> list[datetime]:
    """UTC start times of bookable slots on local dates [first_day, last_day]."""
    earliest = now + min_notice
    slots: set[datetime] = set()
    day = first_day
    while day <= last_day:
        for start_minute, end_minute in day_windows(day, weekly, exceptions):
            window_start = local_to_utc(day, start_minute, tz)
            window_end = local_to_utc(day, end_minute, tz)
            cursor = window_start
            while cursor + duration <= window_end:
                if cursor >= earliest and not _overlaps(cursor, cursor + duration, busy):
                    slots.add(cursor)
                cursor += step
        day += timedelta(days=1)
    return sorted(slots)


def group_by_local_date(slots: Iterable[datetime], tz: ZoneInfo) -> dict[date, list[datetime]]:
    grouped: dict[date, list[datetime]] = {}
    for slot in slots:
        grouped.setdefault(slot.astimezone(tz).date(), []).append(slot)
    return grouped
