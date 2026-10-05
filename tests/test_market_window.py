"""Tests for market window checks (schedule-event cutoff logic)."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from src.trading.execution_status import can_submit_live_orders
from src.trading.us_equity_calendar import is_us_equity_trading_day, nyse_session_close_et

ET = ZoneInfo("America/New_York")


def test_wheel_window_before_open() -> None:
    """Wheel (equity) schedule should abort before market open."""
    dt = datetime(2026, 10, 6, 9, 0, tzinfo=ET)  # Monday 9:00 AM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:30")
    assert not ok
    assert reason == "before_open"


def test_wheel_window_after_open_before_cutoff() -> None:
    """Wheel schedule should proceed between open and 15:30 ET cutoff."""
    dt = datetime(2026, 10, 6, 10, 0, tzinfo=ET)  # Monday 10:00 AM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:30")
    assert ok
    assert reason == "ok"


def test_wheel_window_after_cutoff() -> None:
    """Wheel schedule should abort after 15:30 ET cutoff."""
    dt = datetime(2026, 10, 6, 15, 45, tzinfo=ET)  # Monday 3:45 PM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:30")
    assert not ok
    assert "past_cutoff" in reason


def test_options_window_after_open_before_cutoff() -> None:
    """Options schedule should proceed between open and 15:55 ET cutoff."""
    dt = datetime(2026, 10, 6, 11, 30, tzinfo=ET)  # Monday 11:30 AM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:55")
    assert ok
    assert reason == "ok"


def test_options_window_after_cutoff() -> None:
    """Options schedule should abort after 15:55 ET cutoff."""
    dt = datetime(2026, 10, 6, 16, 10, tzinfo=ET)  # Monday 4:10 PM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:55")
    assert not ok
    assert "past_cutoff" in reason or "after_close" in reason


def test_drip_window_before_open() -> None:
    """Drip schedule should abort before market open."""
    dt = datetime(2026, 10, 7, 9, 15, tzinfo=ET)  # Tuesday 9:15 AM ET
    assert is_us_equity_trading_day(dt)
    ok, reason = can_submit_live_orders(dt, cutoff_et="16:00")
    assert not ok
    assert reason == "before_open"


def test_drip_window_after_open_before_close() -> None:
    """Drip schedule should proceed between open and 16:00 ET close."""
    dt = datetime(2026, 10, 7, 14, 0, tzinfo=ET)  # Tuesday 2:00 PM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="16:00")
    assert ok
    assert reason == "ok"


def test_drip_window_after_close() -> None:
    """Drip schedule should abort after 16:00 ET close."""
    dt = datetime(2026, 10, 7, 16, 30, tzinfo=ET)  # Tuesday 4:30 PM ET
    ok, reason = can_submit_live_orders(dt, cutoff_et="16:00")
    assert not ok
    assert "past_cutoff" in reason or "after_close" in reason


def test_early_close_day_respects_1pm_close() -> None:
    """Cutoff never exceeds early close (13:00 ET)."""
    # Day after Thanksgiving 2026 (Nov 27): early close at 13:00 ET
    dt = datetime(2026, 11, 27, 13, 10, tzinfo=ET)
    assert is_us_equity_trading_day(dt)
    close = nyse_session_close_et(dt)
    assert close == time(13, 0)
    # Even with late cutoff (15:55), should respect early close
    ok, reason = can_submit_live_orders(dt, cutoff_et="15:55")
    assert not ok
    assert "after_early_close" in reason or "after_close" in reason


def test_weekend_always_outside_window() -> None:
    """Weekends should always fail market window check."""
    saturday = datetime(2026, 10, 10, 12, 0, tzinfo=ET)
    assert not is_us_equity_trading_day(saturday)
    ok, reason = can_submit_live_orders(saturday, cutoff_et="15:30")
    assert not ok
    assert "market_closed" in reason


def test_holiday_always_outside_window() -> None:
    """Holidays should always fail market window check."""
    # Labor Day 2026: September 7 (Monday)
    labor_day = datetime(2026, 9, 7, 12, 0, tzinfo=ET)
    assert not is_us_equity_trading_day(labor_day)
    ok, reason = can_submit_live_orders(labor_day, cutoff_et="15:30")
    assert not ok
    assert "market_closed" in reason
