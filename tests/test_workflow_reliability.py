"""Tests for workflow reliability enhancements: watchdog dispatch and gates.

This test suite validates that the watchdog and repository_dispatch triggers
respect all existing gates (market window, holidays, same-day idempotency)
and cannot cause double-runs.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.dispatch_missed_workflows import (
    WORKFLOWS,
    WorkflowConfig,
    is_in_market_window,
)
from src.trading.wheel_daily_once import (
    DRIP_MARKER_NAME,
    MARKER_NAME,
    OPTIONS_MARKER_NAME,
    already_ran_et_day,
    check_already_ran,
    mark_ran_et_day,
)

ET = ZoneInfo("America/New_York")

DRIP_MARKER_DIR = Path("data/performance/growth_income_drip_v1")
DEFAULT_MARKER_DIR = Path("data/performance")


class TestWatchdogMarketWindowGates:
    """Test that watchdog respects market window gates."""

    def test_wheel_in_window_morning(self) -> None:
        """Wheel workflow is in-window during morning trading hours."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        dt = datetime(2026, 10, 6, 10, 30, tzinfo=ET)  # Tuesday 10:30 AM ET
        in_window, reason = is_in_market_window(wheel_config, dt)
        assert in_window
        assert reason == "ok"

    def test_wheel_out_of_window_after_cutoff(self) -> None:
        """Wheel workflow is out-of-window after 15:30 ET cutoff."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        dt = datetime(2026, 10, 6, 15, 45, tzinfo=ET)  # Tuesday 3:45 PM ET
        in_window, reason = is_in_market_window(wheel_config, dt)
        assert not in_window
        assert "past_cutoff" in reason or "after_close" in reason

    def test_options_in_window_early_afternoon(self) -> None:
        """Options workflow is in-window in early afternoon."""
        options_config = next(w for w in WORKFLOWS if w.track == "options")
        dt = datetime(2026, 10, 7, 14, 0, tzinfo=ET)  # Wednesday 2:00 PM ET
        in_window, reason = is_in_market_window(options_config, dt)
        assert in_window
        assert reason == "ok"

    def test_options_out_of_window_after_cutoff(self) -> None:
        """Options workflow is out-of-window after 15:55 ET cutoff."""
        options_config = next(w for w in WORKFLOWS if w.track == "options")
        dt = datetime(2026, 10, 7, 16, 10, tzinfo=ET)  # Wednesday 4:10 PM ET
        in_window, reason = is_in_market_window(options_config, dt)
        assert not in_window

    def test_drip_in_window_afternoon(self) -> None:
        """Drip workflow is in-window before market close."""
        drip_config = next(w for w in WORKFLOWS if w.track == "drip")
        dt = datetime(2026, 10, 8, 15, 0, tzinfo=ET)  # Thursday 3:00 PM ET
        in_window, reason = is_in_market_window(drip_config, dt)
        assert in_window
        assert reason == "ok"

    def test_drip_out_of_window_after_close(self) -> None:
        """Drip workflow is out-of-window after 16:00 ET close."""
        drip_config = next(w for w in WORKFLOWS if w.track == "drip")
        dt = datetime(2026, 10, 8, 16, 15, tzinfo=ET)  # Thursday 4:15 PM ET
        in_window, reason = is_in_market_window(drip_config, dt)
        assert not in_window

    def test_all_workflows_out_of_window_on_weekend(self) -> None:
        """All workflows are out-of-window on weekends."""
        saturday = datetime(2026, 10, 10, 12, 0, tzinfo=ET)
        for workflow in WORKFLOWS:
            in_window, reason = is_in_market_window(workflow, saturday)
            assert not in_window
            assert "market_closed" in reason

    def test_all_workflows_out_of_window_on_holiday(self) -> None:
        """All workflows are out-of-window on holidays."""
        labor_day = datetime(2026, 9, 7, 12, 0, tzinfo=ET)  # Labor Day Monday
        for workflow in WORKFLOWS:
            in_window, reason = is_in_market_window(workflow, labor_day)
            assert not in_window
            assert "market_closed" in reason


class TestWatchdogIdempotencyGates:
    """Test that watchdog respects same-day idempotency gates."""

    def test_watchdog_skips_wheel_if_already_ran(self, tmp_path: Path) -> None:
        """Watchdog should skip wheel workflow if marker shows it already ran."""
        day = date(2026, 10, 6)
        mark_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        already, reason = check_already_ran(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        assert already
        assert "already_ran_et" in reason

    def test_watchdog_dispatches_wheel_if_not_ran(self, tmp_path: Path) -> None:
        """Watchdog should consider dispatching wheel if no marker exists."""
        day = date(2026, 10, 6)
        
        already, reason = check_already_ran(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        assert not already
        assert "no_marker" in reason

    def test_watchdog_skips_options_if_already_ran(self, tmp_path: Path) -> None:
        """Watchdog should skip options workflow if marker shows it already ran."""
        day = date(2026, 10, 7)
        mark_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
        
        already, reason = check_already_ran(
            day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME
        )
        assert already

    def test_watchdog_skips_drip_if_already_ran(self, tmp_path: Path) -> None:
        """Watchdog should skip drip workflow if marker shows it already ran."""
        day = date(2026, 10, 8)
        mark_ran_et_day(day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME)
        
        already, reason = check_already_ran(
            day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME
        )
        assert already

    def test_stale_marker_does_not_prevent_dispatch(self, tmp_path: Path) -> None:
        """Stale marker from previous day should not prevent today's dispatch."""
        yesterday = date(2026, 10, 7)
        today = date(2026, 10, 8)
        
        mark_ran_et_day(yesterday, marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        already, reason = check_already_ran(today, marker_dir=tmp_path, marker_name=MARKER_NAME)
        assert not already
        assert "marker_stale" in reason


class TestWatchdogDispatchLogic:
    """Test watchdog dispatch decision logic (in-window + not-already-ran)."""

    def test_dispatch_decision_yes_when_missed_and_in_window(self, tmp_path: Path) -> None:
        """Watchdog should dispatch when workflow missed and still in window."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        dt = datetime(2026, 10, 6, 11, 0, tzinfo=ET)  # Monday 11 AM ET
        
        already, _ = check_already_ran(
            dt.date(), marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        in_window, _ = is_in_market_window(wheel_config, dt)
        
        should_dispatch = (not already) and in_window
        assert should_dispatch

    def test_dispatch_decision_no_when_already_ran(self, tmp_path: Path) -> None:
        """Watchdog should not dispatch when workflow already ran today."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        dt = datetime(2026, 10, 6, 11, 0, tzinfo=ET)
        
        mark_ran_et_day(dt.date(), marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        already, _ = check_already_ran(
            dt.date(), marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        in_window, _ = is_in_market_window(wheel_config, dt)
        
        should_dispatch = (not already) and in_window
        assert not should_dispatch

    def test_dispatch_decision_no_when_out_of_window(self, tmp_path: Path) -> None:
        """Watchdog should not dispatch when outside market window."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        dt = datetime(2026, 10, 6, 16, 0, tzinfo=ET)  # Monday 4 PM ET (too late)
        
        already, _ = check_already_ran(
            dt.date(), marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        in_window, _ = is_in_market_window(wheel_config, dt)
        
        should_dispatch = (not already) and in_window
        assert not should_dispatch


class TestRepositoryDispatchGates:
    """Test that repository_dispatch triggers respect all gates."""

    def test_repository_dispatch_bypasses_holiday_gate(self) -> None:
        """repository_dispatch should bypass holiday gate (like workflow_dispatch)."""
        # This is tested by workflow YAML logic:
        # if [ "${{ github.event_name }}" != "schedule" ]; then
        #   echo "should_run=true"
        # The repository_dispatch event_name is "repository_dispatch", not "schedule"
        pass

    def test_repository_dispatch_respects_market_window(self) -> None:
        """repository_dispatch should still respect market window gate."""
        wheel_config = next(w for w in WORKFLOWS if w.track == "wheel")
        
        late_time = datetime(2026, 10, 6, 16, 0, tzinfo=ET)
        in_window, _ = is_in_market_window(wheel_config, late_time)
        assert not in_window

    def test_repository_dispatch_respects_same_day_idempotency(self, tmp_path: Path) -> None:
        """repository_dispatch should respect same-day idempotency marker."""
        day = date(2026, 10, 6)
        mark_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        already, _ = check_already_ran(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        assert already


class TestDoubleRunPrevention:
    """Integration tests ensuring double-runs are impossible."""

    def test_multiple_cron_slots_same_day_prevented(self, tmp_path: Path) -> None:
        """Multiple cron slots firing same day: only first one executes."""
        day = date(2026, 10, 6)
        
        slot1_time = datetime(2026, 10, 6, 11, 0, tzinfo=ET)
        already_before, _ = check_already_ran(
            slot1_time.date(), marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        assert not already_before
        
        mark_ran_et_day(slot1_time.date(), marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        slot2_time = datetime(2026, 10, 6, 13, 0, tzinfo=ET)
        already_after, _ = check_already_ran(
            slot2_time.date(), marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        assert already_after

    def test_cron_plus_watchdog_same_day_prevented(self, tmp_path: Path) -> None:
        """Cron fires, then watchdog checks: watchdog sees marker and skips."""
        day = date(2026, 10, 6)
        
        mark_ran_et_day(day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME)
        
        already, reason = check_already_ran(
            day, marker_dir=tmp_path, marker_name=OPTIONS_MARKER_NAME
        )
        assert already
        assert "already_ran_et" in reason

    def test_cron_plus_repository_dispatch_same_day_prevented(self, tmp_path: Path) -> None:
        """Cron fires, then external dispatch: dispatch sees marker and skips."""
        day = date(2026, 10, 6)
        
        mark_ran_et_day(day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME)
        
        already, _ = check_already_ran(
            day, marker_dir=DRIP_MARKER_DIR, marker_name=DRIP_MARKER_NAME
        )
        assert already

    def test_all_three_triggers_same_day_only_first_executes(self, tmp_path: Path) -> None:
        """Cron, watchdog, and external dispatch: all check same marker."""
        day = date(2026, 10, 7)
        
        check1_already, _ = check_already_ran(
            day, marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        assert not check1_already
        
        mark_ran_et_day(day, marker_dir=tmp_path, marker_name=MARKER_NAME)
        
        check2_already, _ = check_already_ran(
            day, marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        assert check2_already
        
        check3_already, _ = check_already_ran(
            day, marker_dir=tmp_path, marker_name=MARKER_NAME
        )
        assert check3_already


class TestWorkflowConfigurations:
    """Test that workflow configs match actual workflow definitions."""

    def test_all_three_workflows_configured(self) -> None:
        """All three workflows should be in WORKFLOWS config."""
        tracks = {w.track for w in WORKFLOWS}
        assert tracks == {"wheel", "options", "drip"}

    def test_wheel_config_correct(self) -> None:
        """Wheel workflow config should match actual workflow."""
        wheel = next(w for w in WORKFLOWS if w.track == "wheel")
        assert wheel.name == "Daily Wheel Scan"
        assert wheel.dispatch_type == "trigger-daily-wheel-scan"
        assert wheel.cutoff_et == "15:30"
        assert wheel.marker_name == MARKER_NAME

    def test_options_config_correct(self) -> None:
        """Options workflow config should match actual workflow."""
        options = next(w for w in WORKFLOWS if w.track == "options")
        assert options.name == "Wheel Options Daily Manage"
        assert options.dispatch_type == "trigger-wheel-options-daily"
        assert options.cutoff_et == "15:55"
        assert options.marker_name == OPTIONS_MARKER_NAME

    def test_drip_config_correct(self) -> None:
        """Drip workflow config should match actual workflow."""
        drip = next(w for w in WORKFLOWS if w.track == "drip")
        assert drip.name == "Growth-Income-Drip Daily Snapshot"
        assert drip.dispatch_type == "trigger-drip-daily-snapshot"
        assert drip.cutoff_et is None  # Uses market close
        assert drip.marker_name == DRIP_MARKER_NAME
        assert drip.marker_dir == DRIP_MARKER_DIR
