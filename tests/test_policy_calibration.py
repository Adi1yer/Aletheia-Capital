"""Tests for learned policy calibration."""

from __future__ import annotations

import src.performance.policy_calibration as pc
from src.performance.policy_calibration import apply_learned_policy, compute_policy


def test_raises_min_buy_when_mid_confidence_buys_lose(monkeypatch):
    fake_rows = [
        {
            "action": "buy",
            "confidence": 75,
            "forward_return_pct": -2.0,
            "executed": True,
            "reason_class": "other",
        }
        for _ in range(8)
    ]
    monkeypatch.setattr(pc, "recent_decisions", lambda weeks=12: fake_rows)
    monkeypatch.setattr(pc, "recent_options", lambda weeks=12: [])

    run_config = {"min_buy_confidence": 60, "min_sell_confidence": 60, "cash_rotation_min_edge": 12}
    policy = compute_policy(run_config)
    assert policy["min_buy_confidence"] >= 62
    assert any(a["knob"] == "min_buy_confidence" for a in policy.get("adjustments", []))


def test_apply_learned_policy_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "POLICY_PATH", tmp_path / "policy.json")
    monkeypatch.setattr(
        pc,
        "compute_policy",
        lambda rc, weeks=12, saved_policy=None: {
            "min_buy_confidence": 90,
            "min_sell_confidence": 60,
            "cash_rotation_min_edge": 25,
            "min_csp_premium_usd": 200,
            "adjustments": [],
            "baseline_source": "cli",
        },
    )
    rc = {"min_buy_confidence": 60}
    apply_learned_policy(rc, recompute=True)
    assert rc["min_buy_confidence"] == 85
    assert rc["cash_rotation_min_edge"] == 20
    assert rc["min_csp_premium_usd"] == 150


def test_policy_persists_from_saved_baseline(monkeypatch):
    saved = {
        "generated_at": "2026-05-20T00:00:00Z",
        "min_buy_confidence": 68,
        "min_sell_confidence": 72,
        "cash_rotation_min_edge": 14,
        "min_csp_premium_usd": 90.0,
    }
    monkeypatch.setattr(pc, "recent_decisions", lambda weeks=12: [])
    monkeypatch.setattr(pc, "recent_options", lambda weeks=12: [])
    base = pc.load_baseline(
        {"min_buy_confidence": 60, "min_sell_confidence": 60, "cash_rotation_min_edge": 12},
        saved,
    )
    assert base["min_buy_confidence"] == 68
    assert base["_baseline_source"] == "saved"
    policy = pc.compute_policy({"min_buy_confidence": 60}, saved_policy=saved)
    assert policy["min_buy_confidence"] == 68
    assert policy["baseline_source"] == "saved"
