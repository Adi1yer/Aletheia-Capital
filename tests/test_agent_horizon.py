"""Horizon-aware agent scoring (Beat SPY)."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.performance.agent_horizon import (
    append_signals_from_run,
    build_horizon_scorecard,
    horizon_buckets_summary,
    horizon_weeks_for_agent,
    min_observations_for_agent,
    resolve_horizon_outcomes,
)


def test_horizon_assignment_defaults():
    assert horizon_weeks_for_agent("technicals_analyst") == 1
    assert horizon_weeks_for_agent("stanley_druckenmiller") == 4
    assert horizon_weeks_for_agent("fundamentals_analyst") == 8
    assert horizon_weeks_for_agent("warren_buffett") == 12
    assert horizon_weeks_for_agent("unknown_agent_xyz") == 4
    assert min_observations_for_agent("technicals_analyst") == 10
    assert min_observations_for_agent("warren_buffett") == 6
    note = horizon_buckets_summary()
    assert "short=1w" in note
    assert "med=4w" in note
    assert "long=" in note


def test_ledger_resolve_short_vs_long(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    run_date = "2026-01-01"
    signals = {
        "technicals_analyst": {
            "AAPL": {"signal": "bullish", "confidence": 80},
        },
        "warren_buffett": {
            "AAPL": {"signal": "bullish", "confidence": 70},
        },
    }
    risk = {"AAPL": {"current_price": 100.0}}
    n = append_signals_from_run(
        run_id="r1",
        run_date=run_date,
        agent_signals=signals,
        risk_analysis=risk,
        ticker_scope=["AAPL"],
        path=ledger,
    )
    assert n == 2

    # One week later: short resolves, Buffett does not.
    week1 = (datetime.fromisoformat(run_date) + timedelta(weeks=1)).strftime("%Y-%m-%d")
    resolved = resolve_horizon_outcomes(
        as_of_date=week1,
        current_prices={"AAPL": 110.0},
        path=ledger,
    )
    assert resolved == 1
    sc = build_horizon_scorecard(
        path=ledger,
        output_path=tmp_path / "sc.json",
    )
    tech = sc["agents"]["technicals_analyst"]
    assert tech["directional_observations"] == 1
    assert tech["directional_accuracy"] == 1.0
    buff = sc["agents"]["warren_buffett"]
    assert buff["directional_observations"] == 0
    assert buff["pending_observations"] == 1

    # Twelve weeks later: Buffett resolves.
    week12 = (datetime.fromisoformat(run_date) + timedelta(weeks=12)).strftime("%Y-%m-%d")
    resolved2 = resolve_horizon_outcomes(
        as_of_date=week12,
        current_prices={"AAPL": 90.0},
        path=ledger,
    )
    assert resolved2 == 1
    sc2 = build_horizon_scorecard(path=ledger, output_path=tmp_path / "sc2.json")
    assert sc2["agents"]["warren_buffett"]["directional_observations"] == 1
    assert sc2["agents"]["warren_buffett"]["directional_accuracy"] == 0.0


def test_weight_update_uses_horizon_min_obs(tmp_path, monkeypatch):
    from src.performance.tracker import PerformanceTracker

    tracker = PerformanceTracker(data_dir=str(tmp_path))
    scorecard = {
        "technicals_analyst": {
            "directional_accuracy": 0.7,
            "directional_observations": 8,
            "confidence_weighted_return_pct": 10.0,
        },
        "warren_buffett": {
            "directional_accuracy": 0.9,
            "directional_observations": 5,
            "confidence_weighted_return_pct": 20.0,
        },
    }
    weights, meta = tracker.calculate_weights_from_performance(
        scorecard_metrics=scorecard,
        current_weights={"technicals_analyst": 1.0, "warren_buffett": 1.0},
        min_observations_for_move=8,
        min_observations_by_agent={
            "technicals_analyst": 10,
            "warren_buffett": 6,
        },
        smoothing_factor=0.2,
        max_weight_delta_per_run=0.15,
    )
    # Technicals has 8 < 10 → skip; Buffett 5 < 6 → skip
    skips = {s["agent"]: s["reason"] for s in meta["weight_skips"]}
    assert skips["technicals_analyst"] == "insufficient_horizon_observations"
    assert skips["warren_buffett"] == "insufficient_horizon_observations"
    assert weights["technicals_analyst"] == 1.0
    assert weights["warren_buffett"] == 1.0

    scorecard["warren_buffett"]["directional_observations"] = 6
    scorecard["technicals_analyst"]["directional_observations"] = 10
    weights2, meta2 = tracker.calculate_weights_from_performance(
        scorecard_metrics=scorecard,
        current_weights={"technicals_analyst": 1.0, "warren_buffett": 1.0},
        min_observations_for_move=8,
        min_observations_by_agent={
            "technicals_analyst": 10,
            "warren_buffett": 6,
        },
        smoothing_factor=0.2,
        max_weight_delta_per_run=0.15,
    )
    assert not any(
        s["agent"] == "warren_buffett" for s in meta2["weight_skips"]
    )
    assert "warren_buffett" in weights2
    # Buffett higher score → weight should move up (or at least not skip)
    assert abs(weights2["warren_buffett"] - 1.0) > 0.01 or any(
        c["agent"] == "warren_buffett" for c in meta2["weight_changes"]
    )


def test_beat_spy_weight_path_uses_horizon_not_freeze(tmp_path, monkeypatch):
    """Beat SPY calls horizon scorecard path instead of freeze skip."""
    from src.trading.pipeline import TradingPipeline

    hz_sc = tmp_path / "agent_horizon_scorecard.json"
    hz_sc.write_text(
        """{
          "source": "agent_horizon_ledger",
          "horizon_note": "Horizon: short=1w / med=4w / long=8–12w",
          "agents": {
            "technicals_analyst": {
              "directional_accuracy": 0.6,
              "directional_observations": 12,
              "confidence_weighted_return_pct": 5.0,
              "eval_horizon_weeks": 1,
              "min_observations_for_move": 10
            }
          }
        }"""
    )
    monkeypatch.setattr(
        "src.performance.agent_horizon.SCORECARD_PATH", hz_sc
    )
    monkeypatch.setattr(
        "src.performance.agent_horizon.load_horizon_scorecard",
        lambda path=hz_sc: __import__("json").loads(hz_sc.read_text()),
    )

    # Avoid promotion gate needing scan cache / writing weights.
    monkeypatch.setattr(
        "src.performance.promotion_gates.evaluate_proposal",
        lambda **kwargs: {"promote": True, "reason": "test"},
    )

    pipe = TradingPipeline(parallel_agents=False)
    # Empty registry weights still ok
    from src.agents.registry import get_registry

    reg = get_registry()
    if "technicals_analyst" not in reg.get_weights():
        from src.agents.technicals_analyst import TechnicalsAnalystAgent

        try:
            reg.register(TechnicalsAnalystAgent(weight=1.0))
        except Exception:
            pass

    meta = pipe._update_agent_weights(
        scan_cache=None,
        run_config={"beat_spy_mode": True},
        learning_context={},
        run_id="test",
        use_horizon_scorecard=True,
    )
    assert meta.get("horizon_mode") is True
    reasons = [s.get("reason") for s in (meta.get("weight_skips") or [])]
    assert "beat_spy_freeze_hit_rate_weights" not in reasons


def test_append_respects_ticker_scope(tmp_path):
    ledger = tmp_path / "l.jsonl"
    n = append_signals_from_run(
        run_id="r2",
        run_date="2026-02-01",
        agent_signals={
            "technicals_analyst": {
                "AAPL": {"signal": "bullish", "confidence": 70},
                "MSFT": {"signal": "bearish", "confidence": 60},
            }
        },
        risk_analysis={
            "AAPL": {"current_price": 100},
            "MSFT": {"current_price": 200},
        },
        ticker_scope=["AAPL"],
        path=ledger,
    )
    assert n == 1
    text = ledger.read_text()
    assert "AAPL" in text
    assert "MSFT" not in text
