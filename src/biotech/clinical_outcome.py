"""Map ClinicalTrials status text to thesis validation outcome tags."""

from __future__ import annotations

from typing import Optional

_SUCCESS = (
    "completed",
    "approved",
    "positive",
    "met primary",
    "met endpoint",
    "successful",
)
_FAIL = (
    "terminated",
    "withdrawn",
    "suspended",
    "negative",
    "failed",
    "did not meet",
    "halted",
)
_MIXED = ("active", "recruiting", "enrolling", "ongoing", "unknown", "not yet")


def clinical_outcome_from_status(status: str) -> str:
    s = (status or "").lower()
    if any(k in s for k in _SUCCESS):
        return "success"
    if any(k in s for k in _FAIL):
        return "fail"
    if any(k in s for k in _MIXED):
        return "mixed"
    return "unknown"


def refresh_trial_status(nct_id: str, company_term: str) -> Optional[str]:
    """Best-effort: find matching trial status by nct_id from a fresh search."""
    if not nct_id.strip():
        return None
    from src.biotech.clinicaltrials import fetch_trial_by_nct_id, search_trials_by_term

    direct = fetch_trial_by_nct_id(nct_id)
    if direct and direct.status:
        return direct.status

    trials = search_trials_by_term(company_term or nct_id, page_size=25)
    for t in trials:
        if (t.nct_id or "").upper() == nct_id.upper():
            return t.status or ""
    return None
