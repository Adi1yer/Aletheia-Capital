"""Learned gates in apply_gates."""

from __future__ import annotations

from src.biotech.calibration import apply_gates
from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot, TrialSummary


def test_learned_prob_mid_gate():
    snap = BiotechSnapshot(
        ticker="X",
        as_of="2026-06-01",
        last_price=10.0,
        trials=[TrialSummary(nct_id="NCT1")],
        filings=[],
    )
    analysis = BiotechAnalysisOutput(no_trade=False, prob_success_low=0.3, prob_success_high=0.38)
    ok, reasons = apply_gates(snap, analysis, policy={"min_llm_prob_mid": 0.45})
    assert ok is False
    assert any("min_llm_prob_mid" in r for r in reasons)
