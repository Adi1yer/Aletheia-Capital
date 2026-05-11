"""Filter trials/snapshots to those in a near-term clinical readout window."""

from __future__ import annotations

import re
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


def trial_phase_number(trial: TrialSummary) -> int:
    """Best-effort numeric phase (0=unknown) from ClinicalTrials phase text."""
    ph = (trial.phase or "").strip()
    if not ph:
        return 0
    nums = [int(m) for m in re.findall(r"phase\s*(\d)", ph, re.I)]
    if nums:
        return max(nums)
    loose = [int(x) for x in re.findall(r"\b([1234])\b", ph)]
    return max(loose) if loose else 0


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
    forward_days_cap: Optional[int] = None,
) -> bool:
    """
    True if the trial's readout date is in the catalyst window:
    from (today - past_grace_days) through (today + forward_days).

    This captures "results expected soon" and "recently passed primary completion
    but data may not be public yet" without going back years.

    If forward_days_cap is set, the upper bound is today + min(forward_days, forward_days_cap)
    (tighter near-term horizon for discovery).
    """
    d = best_readout_date(trial)
    if d is None:
        return False
    lo = today - timedelta(days=max(0, past_grace_days))
    eff_fwd = int(forward_days)
    if forward_days_cap is not None and int(forward_days_cap) > 0:
        eff_fwd = min(eff_fwd, int(forward_days_cap))
    hi = today + timedelta(days=max(0, eff_fwd))
    return lo <= d <= hi


def snapshot_has_readout_catalyst(
    snapshot: BiotechSnapshot,
    today: Optional[date] = None,
    forward_days: int = 120,
    past_grace_days: int = 45,
    min_phase: int = 0,
    readout_max_forward_days: Optional[int] = None,
) -> bool:
    """True if any trial on the snapshot has a readout date in the configured window."""
    today = today or date.today()
    for t in snapshot.trials:
        if min_phase > 0 and trial_phase_number(t) < int(min_phase):
            continue
        if trial_in_readout_window(
            t, today, forward_days, past_grace_days, forward_days_cap=readout_max_forward_days
        ):
            return True
    return False
