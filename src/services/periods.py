"""Period arithmetic for the spending stats: pure functions on local dates.

A period is `(start, end)` with `end` exclusive: a week runs from Monday to the next Monday, a
month from the first to the next first. A period is told apart by its bounds alone: only a month
starts and ends on a first.
"""

from datetime import date, timedelta
from typing import Literal

PeriodKind = Literal["week", "month"]

_WEEK = timedelta(days=7)


def period(kind: PeriodKind, anchor: date) -> tuple[date, date]:
    """The week (Monday to the next Monday) or month (the first to the next first) of `anchor`."""
    if kind == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + _WEEK
    start = anchor.replace(day=1)
    return start, _first_of_next_month(start)


def previous(start: date, end: date) -> tuple[date, date]:
    """The period of the same kind just before `(start, end)`: the previous week or month."""
    if start.day == 1 and end.day == 1:
        return (start - timedelta(days=1)).replace(day=1), start
    return start - _WEEK, start


def is_current(start: date, end: date, today: date) -> bool:
    return start <= today < end


def next_anchor(start: date, end: date) -> date:
    """Any date of the following period: its first day."""
    return end


def previous_anchor(start: date, end: date) -> date:
    """Any date of the preceding period: the day before this one starts."""
    return start - timedelta(days=1)


def _first_of_next_month(first: date) -> date:
    return date(first.year + (first.month == 12), first.month % 12 + 1, 1)
