"""Primary catalyst trial selection."""

from __future__ import annotations

from datetime import date, timedelta

from src.biotech.models import BiotechSnapshot, TrialSummary
from src.biotech.readout_window import primary_catalyst_trial


def test_primary_catalyst_picks_nearest_readout():
    today = date(2026, 6, 1)
    near = (today + timedelta(days=14)).isoformat()
    far = (today + timedelta(days=60)).isoformat()
    snap = BiotechSnapshot(
        ticker="AAA",
        as_of=today.isoformat(),
        trials=[
            TrialSummary(nct_id="NCT1", phase="Phase 2", primary_completion_date=far),
            TrialSummary(nct_id="NCT2", phase="Phase 3", primary_completion_date=near),
        ],
    )
    t = primary_catalyst_trial(snap, today=today, forward_days=120, past_grace_days=45)
    assert t is not None
    assert t.nct_id == "NCT2"
