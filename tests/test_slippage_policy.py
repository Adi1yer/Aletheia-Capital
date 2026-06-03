"""Slippage-driven policy rules."""

from __future__ import annotations

import src.performance.policy_calibration as pc
from src.performance.policy_calibration import compute_policy


def test_rotation_slippage_raises_edge(monkeypatch):
    monkeypatch.setattr(pc, "recent_decisions", lambda weeks=12: [])
    monkeypatch.setattr(pc, "recent_options", lambda weeks=12: [])
    monkeypatch.setattr(
        "src.performance.fill_ledger.slippage_by_reason_class",
        lambda weeks=12: {"cash_rotation": 30.0},
    )
    monkeypatch.setattr("src.performance.counterfactual_ledger.recent_resolved", lambda weeks=12: [])

    run_config = {"min_buy_confidence": 60, "cash_rotation_min_edge": 12}
    policy = compute_policy(run_config, saved_policy={})
    assert policy["cash_rotation_min_edge"] >= 13
