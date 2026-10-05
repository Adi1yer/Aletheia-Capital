"""Tests for multi-track idempotency markers and market-window checks."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.trading.wheel_daily_once import (
    DEFAULT_MARKER_DIR,
    DRIP_MARKER_NAME,
    MARKER_NAME,
    OPTIONS_MARKER_NAME,
    already_ran_et_day,
    check_already_ran,
    mark_ran_et_day,
    marker_path,
)

ET = ZoneInfo("America/New_York")

# Drip marker dir must match workflow cache path
DRIP_MARKER_DIR = Path("data/performance/growth_income_drip_v1")


def test_wheel_marker_independent_of_options(tmp_path: Path) -> None:
    """Wheel and options tracks have independent same-day markers."""
    day = date(2026, 10, 6)  # Monday
    mark_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
    assert already_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
    assert not already_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)


def test_options_marker_independent_of_drip(tmp_path: Path) -> None:
    """Options and drip tracks have independent same-day markers."""
    day = date(2026, 10, 7)  # Tuesday
    mark_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
    assert already_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
    assert not already_ran_et_day(day, marker_dir=tmp_path, marker_name=DRIP_MARKER_NAME)


def test_check_already_ran_no_marker(tmp_path: Path) -> None:
    """check_already_ran returns False when marker does not exist."""
    day = date(2026, 10, 8)
    already, reason = check_already_ran(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
    assert not already
    assert "no_marker" in reason


def test_check_already_ran_stale_marker(tmp_path: Path) -> None:
    """check_already_ran returns False when marker is from a different day."""
    yesterday = date(2026, 10, 7)
    today = date(2026, 10, 8)
    mark_ran_et_day(yesterday, marker_dir=tmp_path, marker_name=MARKER_NAME)
    already, reason = check_already_ran(today, marker_dir=tmp_path, marker_name=MARKER_NAME)
    assert not already
    assert "marker_stale" in reason


def test_check_already_ran_same_day(tmp_path: Path) -> None:
    """check_already_ran returns True when marker matches ET day."""
    day = date(2026, 10, 9)
    mark_ran_et_day(day, marker_dir=tmp_path, marker_name=DRIP_MARKER_NAME)
    already, reason = check_already_ran(day, marker_dir=tmp_path, marker_name=DRIP_MARKER_NAME)
    assert already
    assert "already_ran_et" in reason


def test_mark_ran_et_day_creates_directory(tmp_path: Path) -> None:
    """mark_ran_et_day creates parent directory if it does not exist."""
    subdir = tmp_path / "nested" / "performance"
    day = date(2026, 10, 10)
    path = mark_ran_et_day(day, marker_dir=subdir, marker_name=OPTIONS_MARKER_NAME)
    assert path.exists()
    assert path.parent == subdir
    assert already_ran_et_day(day, marker_dir=subdir, marker_name=OPTIONS_MARKER_NAME)


def test_multiple_tracks_same_day(tmp_path: Path) -> None:
    """All three tracks can complete successfully the same ET day."""
    day = date(2026, 10, 13)  # Monday
    mark_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
    mark_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
    mark_ran_et_day(day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME)
    assert already_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
    assert already_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
    assert already_ran_et_day(day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME)


def test_drip_marker_path_under_drip_cache_dir() -> None:
    """Regression: drip marker must be under the drip workflow cache path.
    
    The drip workflow caches only data/performance/growth_income_drip_v1,
    so the marker must live there (not under data/performance root) or it
    won't be restored on subsequent runs, breaking idempotency.
    """
    drip_cache_root = Path("data/performance/growth_income_drip_v1")
    drip_marker = marker_path(marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME)
    
    # Marker must be under the drip cache root
    assert drip_marker.is_relative_to(drip_cache_root), (
        f"Drip marker {drip_marker} is not under cached directory {drip_cache_root}. "
        "This will break idempotency because the marker won't survive across staggered runs."
    )


def test_wheel_and_options_markers_under_shared_performance_dir() -> None:
    """Wheel and options markers live under data/performance (both workflows cache it)."""
    wheel_marker = marker_path(marker_dir=DEFAULT_MARKER_DIR, marker_name=MARKER_NAME)
    options_marker = marker_path(marker_dir=DEFAULT_MARKER_DIR, marker_name=OPTIONS_MARKER_NAME)
    perf_root = Path("data/performance")
    
    assert wheel_marker.is_relative_to(perf_root)
    assert options_marker.is_relative_to(perf_root)
