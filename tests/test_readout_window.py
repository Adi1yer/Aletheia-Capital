"""Tests for biotech readout window filtering."""

from datetime import date, timedelta

from src.biotech.models import BiotechSnapshot, TrialSummary
from src.biotech.readout_window import (
    best_readout_date,
    snapshot_has_readout_catalyst,
    trial_in_readout_window,
)


def test_trial_in_window_future():
    today = date(2025, 6, 1)
    t = TrialSummary(
        nct_id="NCT1",
        primary_completion_date="2025-07-15",
    )
    assert trial_in_readout_window(t, today, forward_days=120, past_grace_days=30) is True


def test_trial_outside_future_horizon():
    today = date(2025, 6, 1)
    t = TrialSummary(
        nct_id="NCT1",
        primary_completion_date="2027-01-01",
    )
    assert trial_in_readout_window(t, today, forward_days=120, past_grace_days=30) is False


def test_trial_grace_past_completion():
    today = date(2025, 6, 1)
    t = TrialSummary(
        nct_id="NCT1",
        primary_completion_date="2025-05-15",
    )
    assert trial_in_readout_window(t, today, forward_days=120, past_grace_days=45) is True


def test_best_readout_prefers_primary():
    t = TrialSummary(
        primary_completion_date="2025-08-01",
        completion_date="2025-12-01",
    )
    assert best_readout_date(t) == date(2025, 8, 1)


def test_snapshot_has_catalyst():
    snap = BiotechSnapshot(
        ticker="X",
        as_of="2025-06-01",
        trials=[
            TrialSummary(
                nct_id="a", primary_completion_date=(date.today() + timedelta(days=30)).isoformat()
            )
        ],
    )
    assert (
        snapshot_has_readout_catalyst(
            snap, today=date.today(), forward_days=120, past_grace_days=30
        )
        is True
    )


def test_snapshot_min_phase_filters_phase1():
    today = date(2025, 6, 1)
    snap = BiotechSnapshot(
        ticker="X",
        as_of="2025-06-01",
        trials=[
            TrialSummary(
                nct_id="a",
                phase="Phase 1",
                primary_completion_date="2025-07-15",
            )
        ],
    )
    assert snapshot_has_readout_catalyst(
        snap, today=today, forward_days=120, past_grace_days=30, min_phase=2
    ) is False
    assert snapshot_has_readout_catalyst(
        snap, today=today, forward_days=120, past_grace_days=30, min_phase=1
    ) is True


def test_readout_forward_cap_excludes_far_trial():
    today = date(2025, 6, 1)
    # Within 120d window from 2025-06-01 but beyond 60d cap.
    t = TrialSummary(nct_id="NCT1", primary_completion_date="2025-08-15")
    assert trial_in_readout_window(t, today, forward_days=120, past_grace_days=30) is True
    assert (
        trial_in_readout_window(
            t, today, forward_days=120, past_grace_days=30, forward_days_cap=60
        )
        is False
    )
