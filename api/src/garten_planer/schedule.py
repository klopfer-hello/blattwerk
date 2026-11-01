"""Date logic of the to-do engine (pure, no DB).

A task's timing is `once` (a date), `yearly` (a month window, may wrap the year
end: Nov-Feb; or, with a phenological trigger, a window from the phase start of that
year, the month window being the fallback, M7) or `interval` (every n days, counted from the day the previous
occurrence was done or skipped; optionally another n in Nov-Feb and only in a month window, M11).
`occurrences()` lists what should exist as a to-do today (current/upcoming within HORIZON_DAYS; past yearly
windows are not created after the fact, an overdue `once` is). `period` is the stable key of an
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
    winter_interval_days: int | None = None  # Nov-Feb instead of interval_days (indoor watering)
    start_date: date | None = None
    pheno_phase: str | None = None  # e.g. "erstfruehling": from the Forsythia blossom
    pheno_offset: int = 0  # days after (negative: before) the phase start
    pheno_window: int = 14  # days the to-do stays due


@dataclass(frozen=True)
class Occurrence:
    period: str
    due_from: date
    due_to: date
    reason: str = ""  # set when a rule moved or shortened the window (legal.py)


Adjust = Callable[[date, date], tuple[date, date, str]]
PhaseStart = Callable[[int], date | None]  # year -> start of the task's phase (observed, reported or expected)


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


WINTER = (11, 12, 1, 2)


def in_months(day: date, month_from: int, month_to: int) -> bool:
    if month_from <= month_to:
        return month_from <= day.month <= month_to
    return day.month >= month_from or day.month <= month_to


def in_season(t: TaskTiming, day: date) -> date:
    """An interval with a month window (fertilise Apr-Sep) rests outside it: the first day of the window."""
    if t.month_from is None or t.month_to is None or in_months(day, t.month_from, t.month_to):
        return day
    year = day.year if day.month < t.month_from else day.year + 1
    return date(year, t.month_from, 1)


def rhythm_field(closed_on: date, t: TaskTiming) -> str:
    """Which interval the next occurrence uses: the winter one when it would fall in Nov-Feb."""
    assert t.interval_days is not None
    winter = t.winter_interval_days and (closed_on + timedelta(days=t.interval_days)).month in WINTER
    return "winter_interval_days" if winter else "interval_days"


def interval_after(closed_on: date, t: TaskTiming) -> Occurrence:
    days: int = getattr(t, rhythm_field(closed_on, t))
    start = in_season(t, closed_on + timedelta(days=days))
    return Occurrence(start.isoformat(), start, start + timedelta(days=_slack(days)))


def yearly_span(t: TaskTiming, year: int, phase_start: PhaseStart | None) -> tuple[date, date]:
    assert t.month_from is not None and t.month_to is not None
    start = phase_start(year) if t.pheno_phase and phase_start else None
    if start is None:
        return yearly_window(year, t.month_from, t.month_to)
    first = start + timedelta(days=t.pheno_offset)
    return first, first + timedelta(days=t.pheno_window)


def occurrences(
    t: TaskTiming,
    today: date,
    adjust: Adjust | None = None,
    horizon_days: int = HORIZON_DAYS,
    phase_start: PhaseStart | None = None,
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
            o = _apply(Occurrence(str(year), *yearly_span(t, year, phase_start)), adjust)
            if o.due_to >= today and o.due_from <= horizon:
                out.append(o)
        return out
    assert t.interval_days is not None
    start = in_season(t, t.start_date or today)
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
    if t.winter_interval_days or t.month_from is not None:  # seasonal: step like the to-dos do
        found: set[int] = set()
        day = in_season(t, max(first, jan1 - timedelta(days=400)))
        while day.year <= year:
            if day.year == year:
                found.add(day.month)
            day = interval_after(day, t).due_from
        return sorted(found)
    if first < jan1:  # jump to the first occurrence in `year` arithmetically, not day by day
        steps = -(-(jan1 - first).days // t.interval_days)
        first += timedelta(days=steps * t.interval_days)
    months: set[int] = set()
    day = first
    while day.year == year:
        if t.month_from is None or t.month_to is None or in_months(day, t.month_from, t.month_to):
            months.add(day.month)
        day += timedelta(days=t.interval_days)
    return sorted(months)
