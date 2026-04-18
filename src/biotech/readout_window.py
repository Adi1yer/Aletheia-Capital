"""Filter trials/snapshots to those in a near-term clinical readout window."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from src.biotech.models import BiotechSnapshot, TrialSummary


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD from ClinicalTrials date strings."""
    if not s or not str(s).strip():
        return None
    raw = str(s).strip().replace("Z", "")
    raw = raw[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def best_readout_date(trial: TrialSummary) -> Optional[date]:
    """Prefer primary completion; fall back to study completion."""
    for key in ("primary_completion_date", "completion_date"):
        val = getattr(trial, key, None) or ""
        d = parse_iso_date(val)
        if d is not None:
            return d
    return None


def trial_in_readout_window(
    trial: TrialSummary,
    today: date,
    forward_days: int,
    past_grace_days: int,
) -> bool:
    """
    True if the trial's readout date is in the catalyst window:
    from (today - past_grace_days) through (today + forward_days).

    This captures "results expected soon" and "recently passed primary completion
    but data may not be public yet" without going back years.
    """
    d = best_readout_date(trial)
    if d is None:
        return False
    lo = today - timedelta(days=max(0, past_grace_days))
    hi = today + timedelta(days=max(0, forward_days))
    return lo <= d <= hi


def snapshot_has_readout_catalyst(
    snapshot: BiotechSnapshot,
    today: Optional[date] = None,
    forward_days: int = 120,
    past_grace_days: int = 45,
) -> bool:
    """True if any trial on the snapshot has a readout date in the configured window."""
    today = today or date.today()
    for t in snapshot.trials:
        if trial_in_readout_window(t, today, forward_days, past_grace_days):
            return True
    return False
