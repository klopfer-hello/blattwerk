"""Date logic of the to-do engine (pure, no DB).

A task's timing is `once` (a date), `yearly` (a month window, may wrap the year
end: Nov-Feb) or `interval` (every n days, counted from the day the previous
occurrence was done or skipped). `occurrences()` lists what should exist as a
to-do today (current/upcoming within HORIZON_DAYS; past yearly windows are not
created after the fact, an overdue `once` is). `period` is the stable key of an
occurrence (UNIQUE per task in the DB), so creating them is idempotent."""

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

HORIZON_DAYS = 60
Recurrence = Literal["once", "yearly", "interval"]


@dataclass(frozen=True)
class TaskTiming:
    recurrence: Recurrence
    due_date: date | None = None
    month_from: int | None = None
    month_to: int | None = None
    interval_days: int | None = None
    start_date: date | None = None


@dataclass(frozen=True)
class Occurrence:
    period: str
    due_from: date
    due_to: date
    reason: str = ""  # set when a rule moved or shortened the window (legal.py)


Adjust = Callable[[date, date], tuple[date, date, str]]


def _apply(o: Occurrence, adjust: Adjust | None) -> Occurrence:
    if adjust is None:
        return o
    start, end, reason = adjust(o.due_from, o.due_to)
    return Occurrence(o.period, start, end, reason)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def yearly_window(year: int, month_from: int, month_to: int) -> tuple[date, date]:
    end_year = year + 1 if month_to < month_from else year
    return date(year, month_from, 1), _month_end(end_year, month_to)


def _slack(days: int) -> int:
    """Days an interval to-do stays 'due' before it counts as overdue."""
    return min(6, days // 7)


def interval_after(closed_on: date, days: int) -> Occurrence:
    start = closed_on + timedelta(days=days)
    return Occurrence(start.isoformat(), start, start + timedelta(days=_slack(days)))


def occurrences(
    t: TaskTiming, today: date, adjust: Adjust | None = None, horizon_days: int = HORIZON_DAYS
) -> list[Occurrence]:
    """`adjust` (the legal rules) runs before the relevance check, so a June window
    moved to October is still created in October."""
    horizon = today + timedelta(days=horizon_days)
    if t.recurrence == "once":
        assert t.due_date is not None
        o = _apply(Occurrence("once", t.due_date, t.due_date), adjust)
        return [o] if o.due_from <= horizon else []
    if t.recurrence == "yearly":
        assert t.month_from is not None and t.month_to is not None
        out = []
        for year in (today.year - 1, today.year, today.year + 1):
            o = _apply(Occurrence(str(year), *yearly_window(year, t.month_from, t.month_to)), adjust)
            if o.due_to >= today and o.due_from <= horizon:
                out.append(o)
        return out
    assert t.interval_days is not None
    start = t.start_date or today
    o = _apply(Occurrence(start.isoformat(), start, start + timedelta(days=_slack(t.interval_days))), adjust)
    return [o] if o.due_from <= horizon else []


def months_in_year(t: TaskTiming, year: int) -> list[int]:
    """Months (1-12) of `year` in which the task is due: the projected calendar."""
    if t.recurrence == "once":
        assert t.due_date is not None
        return [t.due_date.month] if t.due_date.year == year else []
    if t.recurrence == "yearly":
        assert t.month_from is not None and t.month_to is not None
        if t.month_from <= t.month_to:
            return list(range(t.month_from, t.month_to + 1))
        return sorted({*range(t.month_from, 13), *range(1, t.month_to + 1)})
    assert t.interval_days is not None
    first, jan1 = t.start_date or date(year, 1, 1), date(year, 1, 1)
    if first < jan1:  # jump to the first occurrence in `year` arithmetically, not day by day
        steps = -(-(jan1 - first).days // t.interval_days)
        first += timedelta(days=steps * t.interval_days)
    months: set[int] = set()
    day = first
    while day.year == year:
        months.add(day.month)
        day += timedelta(days=t.interval_days)
    return sorted(months)
