"""Biotech policy learning from closed thesis rows."""

from __future__ import annotations

from src.biotech.policy_learning import compute_biotech_policy


def _closed_row(ticker: str, arm: str, pnl: float, prob_lo: float, prob_hi: float, phase: str = "Phase 2"):
    return {
        "ticker": ticker,
        "arm": arm,
        "run_date": "2026-05-01",
        "nct_id": f"NCT-{ticker}",
        "status": "closed",
        "premium_filled_usd": 400.0,
        "pnl_pct_of_premium": pnl,
        "llm_prob_low": prob_lo,
        "llm_prob_high": prob_hi,
        "phase": phase,
        "underlying_px_entry": 100.0,
        "underlying_px_5d": 110.0 if pnl > 0 else 90.0,
    }


def test_compute_raises_min_llm_prob_mid(monkeypatch):
    rows = [
        _closed_row(f"X{i}", "llm_gated", -20.0, 0.35, 0.42)
        for i in range(5)
    ]
    import src.biotech.policy_learning as pl

    monkeypatch.setattr(pl, "closed_rows", lambda weeks=24: rows)
    result = compute_biotech_policy(weeks=52)
    knobs = {a["knob"] for a in result.get("adjustments") or []}
    assert "min_llm_prob_mid" in knobs or result["policy"]["min_llm_prob_mid"] >= 0.45
