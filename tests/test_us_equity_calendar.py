from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.trading.us_equity_calendar import (
    first_us_equity_session_of_week,
    is_first_us_equity_session_of_week,
    is_us_equity_trading_day,
    nyse_full_day_closures,
    should_run_daily_trading_session,
    should_run_weekly_scan,
)


def test_labor_day_2026_closed_and_defers_to_tuesday():
    labor = date(2026, 9, 7)
    assert labor in nyse_full_day_closures(2026)
    assert is_us_equity_trading_day(labor) is False
    assert should_run_weekly_scan(labor) == (False, "market_closed:2026-09-07")
    assert first_us_equity_session_of_week(labor) == date(2026, 9, 8)
    assert is_first_us_equity_session_of_week(date(2026, 9, 8)) is True
    assert should_run_weekly_scan(date(2026, 9, 8))[0] is True


def test_normal_monday_runs_tuesday_skips():
    monday = date(2026, 9, 14)
    tuesday = date(2026, 9, 15)
    assert is_us_equity_trading_day(monday) is True
    assert should_run_weekly_scan(monday)[0] is True
    assert should_run_weekly_scan(tuesday)[0] is False
    assert "not_first_session" in should_run_weekly_scan(tuesday)[1]


def test_good_friday_2026_and_mlk():
    assert date(2026, 4, 3) in nyse_full_day_closures(2026)  # Good Friday
    assert date(2026, 1, 19) in nyse_full_day_closures(2026)  # MLK


def test_new_years_observed_on_friday_when_saturday():
    # Jan 1 2033 is a Saturday → observed Fri Dec 31 2032
    assert date(2032, 12, 31) in nyse_full_day_closures(2032)


def test_et_datetime_uses_america_new_york_date():
    # 2026-09-08 01:00 UTC is still 2026-09-07 evening ET (Labor Day).
    dt = datetime(2026, 9, 8, 1, 0, tzinfo=ZoneInfo("UTC"))
    assert is_us_equity_trading_day(dt) is False
    assert should_run_weekly_scan(dt)[0] is False


def test_daily_gate_runs_every_open_weekday():
    labor = date(2026, 9, 7)
    tuesday = date(2026, 9, 15)
    monday = date(2026, 9, 14)
    weekend = date(2026, 9, 19)  # Saturday
    assert should_run_daily_trading_session(labor)[0] is False
    assert "market_closed" in should_run_daily_trading_session(labor)[1]
    assert should_run_daily_trading_session(weekend)[0] is False
    assert should_run_daily_trading_session(monday)[0] is True
    assert should_run_daily_trading_session(tuesday)[0] is True
    assert "trading_session" in should_run_daily_trading_session(tuesday)[1]
