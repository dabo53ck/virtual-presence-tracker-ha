"""Time windows of the presence sources (M5).

A tracker with time windows has one window per weekday, a start and an end on
the wall clock. Start = end means no window that day; an end before the start
runs past midnight and belongs to the day it starts on, so Monday `22:00` to
`06:00` is Monday 22:00 to Tuesday 06:00. A window contains its start and not
its end.

Nothing here knows Home Assistant: it parses the stored keys and answers "is
this moment in a window?" and "when is the next start or end?", for the
follower (presence.py) and the diagnostics, and for tests without a running
instance. The moments it is given are aware datetimes in the local time zone,
so a window follows the wall clock across a change of daylight saving time: a
time the clocks skip counts from the moment of the jump, a time they repeat at
its first occurrence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from .const import (
    CONF_USE_TIME_WINDOWS,
    DEFAULT_USE_TIME_WINDOWS,
    DEFAULT_WINDOW_TIME,
    WINDOW_DAY_KEYS,
)


@dataclass(frozen=True, slots=True)
class Window:
    """The window of one weekday, on the wall clock."""

    start: time
    end: time

    @property
    def empty(self) -> bool:
        """Return whether there is no window that day: start = end."""
        return self.start == self.end

    @property
    def past_midnight(self) -> bool:
        """Return whether the window ends on the next day."""
        return self.end < self.start

    def describe(self) -> str:
        """Return the window as `HH:MM-HH:MM`, or `none` without one."""
        if self.empty:
            return "none"
        return f"{self.start:%H:%M}-{self.end:%H:%M}"


# Seven windows, Monday first: the index is `datetime.weekday()`.
type Windows = tuple[Window, ...]


def parse_time(value: Any) -> time:
    """Return a stored time, or midnight when it is missing or unreadable.

    Midnight is what a missing key means, and start = end = midnight is "no
    window": a value that cannot be read never opens a window by accident.
    """
    if isinstance(value, time):
        return value.replace(tzinfo=None)
    try:
        return time.fromisoformat(str(value)).replace(tzinfo=None)
    except ValueError:
        return time.fromisoformat(DEFAULT_WINDOW_TIME)


def enabled(data: Mapping[str, Any]) -> bool:
    """Return whether a tracker's subentry data has its time windows on."""
    return bool(data.get(CONF_USE_TIME_WINDOWS, DEFAULT_USE_TIME_WINDOWS))


def parse(data: Mapping[str, Any]) -> Windows:
    """Return the seven windows a tracker's subentry data describes."""
    return tuple(
        Window(
            parse_time(data.get(start_key, DEFAULT_WINDOW_TIME)),
            parse_time(data.get(end_key, DEFAULT_WINDOW_TIME)),
        )
        for start_key, end_key in WINDOW_DAY_KEYS
    )


def in_window(windows: Windows, now: datetime) -> bool:
    """Return whether a moment lies in a window.

    Today's window, or yesterday's if it runs past midnight, start included
    and end excluded. Compared as moments rather than on the wall clock, so
    that a time the clocks repeat in autumn counts once, at its first
    occurrence, and one they skip in spring at the moment of the jump - the
    same moments `next_boundary()` sets its timers to.
    """
    after = now.astimezone(UTC)
    return any(
        start <= after < end for start, end in _moments(windows, now, range(-1, 1))
    )


def next_boundary(windows: Windows, now: datetime) -> datetime | None:
    """Return the next start or end of a window after `now`, or None.

    In the time zone of `now`. None when no day has a window.
    """
    after = now.astimezone(UTC)
    # From yesterday, whose window may end today, to a week ahead, which is
    # always far enough to reach the next boundary of any day.
    found = min(
        (
            moment
            for pair in _moments(windows, now, range(-1, 8))
            for moment in pair
            if moment > after
        ),
        default=None,
    )
    return found.astimezone(now.tzinfo) if found is not None else None


def _moments(
    windows: Windows, now: datetime, offsets: range
) -> list[tuple[datetime, datetime]]:
    """Return start and end, in UTC, of every window of the days around `now`.

    `offsets` are days relative to the day of `now`; a day without a window
    has none.
    """
    zone = now.tzinfo
    moments: list[tuple[datetime, datetime]] = []
    for offset in offsets:
        day = now.date() + timedelta(days=offset)
        window = windows[day.weekday()]
        if window.empty:
            continue
        end_day = day + timedelta(days=1) if window.past_midnight else day
        moments.append((_at(day, window.start, zone), _at(end_day, window.end, zone)))
    return moments


def _at(day: date, clock: time, zone: Any) -> datetime:
    """Return the moment, in UTC, a wall clock shows a time on a day.

    A time that comes twice on the day the clocks go back is its first
    occurrence. A time the clocks skip on the day they go forward is the
    moment of the jump: 02:30 in a gap from 02:00 to 03:00 is 03:00.
    """
    first = datetime.combine(day, clock, tzinfo=zone).astimezone(UTC)
    later = datetime.combine(day, clock, tzinfo=zone).replace(fold=1).astimezone(UTC)
    if later >= first:
        # Not in a gap: fold 0 is the time, or its first occurrence.
        return first
    # In a gap, fold 1 reads the time with the offset after the jump and lands
    # before it, fold 0 with the offset before and lands after. The jump lies
    # in between: the first second whose offset is the later one.
    offset_after = first.astimezone(zone).utcoffset()
    low, high = 0, int((first - later).total_seconds())
    while low < high:
        middle = (low + high) // 2
        if (later + timedelta(seconds=middle)).astimezone(zone).utcoffset() == (
            offset_after
        ):
            high = middle
        else:
            low = middle + 1
    return later + timedelta(seconds=low)
