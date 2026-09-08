"""NYSE regular-session calendar (stdlib only).

Used by the weekly Actions gate so a Monday market holiday defers the run to
the next open session (usually Tuesday), without adding calendar dependencies.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional, Set, Union
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

DateLike = Union[date, datetime]


def _as_et_date(value: DateLike) -> date:
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ET).date()
    return value


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the n-th weekday in month (weekday: Mon=0 … Sun=6)."""
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    d = d + timedelta(days=offset)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed_fixed(d: date) -> date:
    """NYSE observed rule for fixed-date holidays (Sat→Fri, Sun→Mon)."""
    if d.weekday() == 5:  # Saturday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday
        return d + timedelta(days=1)
    return d


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm (Western Easter)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def nyse_full_day_closures(year: int) -> Set[date]:
    """Full-session NYSE closures for ``year`` (excludes early-close days)."""
    closures: Set[date] = {
        _observed_fixed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, 0, 3),  # MLK Day
        _nth_weekday(year, 2, 0, 3),  # Presidents Day
        _easter_sunday(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed_fixed(date(year, 6, 19)),  # Juneteenth
        _observed_fixed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed_fixed(date(year, 12, 25)),  # Christmas
    }
    # New Year's observed on prior Dec 31 when Jan 1 is Saturday.
    prior_nye = _observed_fixed(date(year + 1, 1, 1))
    if prior_nye.year == year:
        closures.add(prior_nye)
    return closures


def _closures_covering(d: date) -> Set[date]:
    return nyse_full_day_closures(d.year - 1) | nyse_full_day_closures(d.year) | nyse_full_day_closures(
        d.year + 1
    )


def is_us_equity_trading_day(value: DateLike) -> bool:
    """True if NYSE has a regular (or early-close) session on this calendar day."""
    d = _as_et_date(value)
    if d.weekday() >= 5:
        return False
    return d not in _closures_covering(d)


def iter_us_equity_trading_days(
    start: DateLike,
    *,
    limit: int = 366,
) -> Iterable[date]:
    d = _as_et_date(start)
    seen = 0
    while seen < limit:
        if is_us_equity_trading_day(d):
            yield d
            seen += 1
        d += timedelta(days=1)


def first_us_equity_session_of_week(value: DateLike) -> Optional[date]:
    """Monday–Friday: earliest NYSE session in the calendar week containing ``value``."""
    d = _as_et_date(value)
    monday = d - timedelta(days=d.weekday())
    for i in range(5):
        candidate = monday + timedelta(days=i)
        if is_us_equity_trading_day(candidate):
            return candidate
    return None


def is_first_us_equity_session_of_week(value: DateLike) -> bool:
    """True when ``value`` is the week's first NYSE session (holiday Monday → Tuesday)."""
    d = _as_et_date(value)
    first = first_us_equity_session_of_week(d)
    return first is not None and d == first


def should_run_weekly_scan(value: Optional[DateLike] = None) -> tuple[bool, str]:
    """
    Whether the scheduled weekly scan should execute on this ET calendar day.

    Runs on the first US equity session of the ISO/calendar week (Mon–Sun by weekday).
    """
    d = _as_et_date(value or datetime.now(tz=ET))
    if not is_us_equity_trading_day(d):
        return False, f"market_closed:{d.isoformat()}"
    first = first_us_equity_session_of_week(d)
    if first is None:
        return False, f"no_session_this_week:{d.isoformat()}"
    if d != first:
        return False, f"not_first_session:{d.isoformat()}:first={first.isoformat()}"
    return True, f"first_session:{d.isoformat()}"
