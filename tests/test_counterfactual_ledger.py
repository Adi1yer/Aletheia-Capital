"""Tests for counterfactual ledger."""

from __future__ import annotations

from src.performance.counterfactual_ledger import (
    append_counterfactuals_from_run,
    resolve_pending_outcomes,
)


def test_counterfactual_append_and_resolve(tmp_path):
    path = tmp_path / "cf.jsonl"
    append_counterfactuals_from_run(
        run_id="r1",
        run_date="2026-05-12",
        decisions={"ZZZ": {"action": "hold", "quantity": 0}},
        aggregated_signals={
            "ZZZ": {"signal": "bullish", "confidence": 75},
        },
        risk_analysis={"ZZZ": {"current_price": 100.0}},
        path=path,
    )
    n = resolve_pending_outcomes({"ZZZ": 110.0}, "2026-05-19", path=path)
    assert n == 1
