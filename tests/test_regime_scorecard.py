"""Regime-split scorecard and weight blending."""

from __future__ import annotations

from src.backtesting.agent_evaluator import blend_scorecard_metrics
from src.performance.weekly_ledger import append_ledger_entry, evaluate_ledger_scorecard


def test_ledger_scorecard_by_regime(tmp_path):
    ledger = tmp_path / "weekly_ledger.jsonl"
    for i, (regime, p1) in enumerate([("accumulate", 55.0), ("accumulate", 60.0)], start=1):
        append_ledger_entry(
            run_id=f"r{i}",
            run_date=f"2026-05-{10+i}",
            active_agents=["growth"],
            regime=regime,
            tickers={
                "AAA": {
                    "price": p1 if i > 1 else 50.0,
                    "agent_signals": {
                        "growth": {"signal": "bullish", "confidence": 80},
                    },
                }
            },
            path=ledger,
        )
    sc = evaluate_ledger_scorecard(path=ledger, min_regime_obs=1)
    assert "growth" in (sc.get("agents") or {})
    assert "accumulate" in (sc.get("by_regime") or {})


def test_blend_scorecard_metrics():
    sc = {
        "agents": {
            "a": {"directional_accuracy": 0.5, "directional_observations": 20, "confidence_weighted_return_pct": 1.0},
        },
        "by_regime": {
            "accumulate": {
                "agents": {
                    "a": {"directional_accuracy": 0.8, "directional_observations": 10, "confidence_weighted_return_pct": 3.0},
                }
            }
        },
    }
    blended = blend_scorecard_metrics(sc, "accumulate")
    assert blended["a"]["directional_accuracy"] > 0.5
