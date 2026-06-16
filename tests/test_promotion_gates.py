"""Tests for promotion gates."""

from __future__ import annotations

from src.performance.promotion_gates import evaluate_proposal, set_calibration_hold, calibration_hold_active


def test_promotion_insufficient_pairs():
    result = evaluate_proposal(proposed_weights={"a": 1.1}, scan_cache=None)
    assert result["promote"] is False
    assert result["reason"] == "insufficient_pairs_for_holdout"


def test_calibration_hold_blocks(tmp_path, monkeypatch):
    hold = tmp_path / "hold.json"
    monkeypatch.setattr("src.performance.promotion_gates.HOLD_PATH", hold)
    set_calibration_hold(True, reason="test", path=hold)
    assert calibration_hold_active(path=hold) is True
    result = evaluate_proposal(proposed_weights={"a": 1.0}, scan_cache=None)
    assert result["promote"] is False
    assert result["reason"] == "calibration_hold_active"


def test_holdout_minimum_evidence_blocks():
    class FakeCache:
        def list_runs(self, limit=13):
            return [{"run_id": "a", "run_date": "2026-01-01"}, {"run_id": "b", "run_date": "2026-01-08"}]

        def load_run(self, run_id):
            return {
                "risk": {"AAPL": {"current_price": 100.0}},
                "signals": {"growth": {"AAPL": {"signal": "bullish", "confidence": 80}}},
            }

    out = evaluate_proposal(
        proposed_weights={"growth": 1.2},
        proposed_policy={"min_holdout_observations": 10},
        scan_cache=FakeCache(),
        holdout_pairs=1,
        total_pairs=2,
    )
    assert out["promote"] is False
