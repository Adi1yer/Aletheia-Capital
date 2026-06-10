"""Dual-arm execution: mechanical always, llm_gated only when gates pass."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.biotech.calibration import apply_gates
from src.biotech.models import BiotechAnalysisOutput, BiotechSnapshot


def test_llm_gated_skipped_when_no_trade():
    from src.biotech.models import FilingRef, TrialSummary

    snap = BiotechSnapshot(
        ticker="X",
        as_of="2026-06-01",
        last_price=10.0,
        trials=[TrialSummary(nct_id="NCT1", phase="Phase 2")],
        filings=[FilingRef(form="8-K", filed_at="2026-01-01", url="http://x")],
    )
    analysis = BiotechAnalysisOutput(no_trade=True, no_trade_reasons=["insufficient data"])
    ok, reasons = apply_gates(snap, analysis)
    assert ok is False
    assert reasons


def test_mechanical_arm_ignores_no_trade_gate():
    """Mechanical path uses gates_ok=True in orchestrator — verify helper contract."""
    broker = MagicMock()
    snap = BiotechSnapshot(ticker="MRNA", as_of="2026-06-01", last_price=50.0)
    analysis = BiotechAnalysisOutput(no_trade=True)
    budget = MagicMock()
    filled = {
        "status": "filled",
        "premium_est_usd": 200,
        "premium_filled_usd": 200,
        "strategy": {"type": "long_straddle", "call_contract": "C", "put_contract": "P"},
        "orders": [],
    }
    with patch("src.biotech.execution.execute_straddle_paper", return_value=filled) as ex:
        with patch("src.biotech.thesis_ledger.append_thesis_entry", return_value="tid") as ap:
            from biotech_catalyst_scan import _execute_arm

            res, tid = _execute_arm(
                "mechanical",
                broker,
                snap,
                analysis,
                budget,
                gates_ok=True,
                gate_reasons=[],
                run_id="r1",
                run_date="2026-06-01",
                catalyst={"nct_id": "NCT1"},
            )
            assert res["status"] == "filled"
            assert tid == "tid"
            ap.assert_called_once()
