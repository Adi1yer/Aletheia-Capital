"""Tests for Beat SPY factor engine and scorecard."""

from __future__ import annotations

from src.alpha.agent_overlay import apply_agent_overlay
from src.alpha.candidate_set import build_candidate_set
from src.alpha.factors import composite_mu, rank_universe, score_ticker_from_dossier
from src.performance.beat_spy_scorecard import build_beat_spy_scorecard
from src.portfolio.beat_spy_policy import apply_beat_spy_defaults


def test_factor_scores_from_dossier():
    dossier = {
        "trends": {"return_1m_pct": 5.0, "return_3m_pct": 10.0},
        "metrics": [{"return_on_equity": 20.0, "price_to_earnings": 15.0}],
    }
    fac = score_ticker_from_dossier(dossier)
    assert fac["momentum"] > 0
    assert composite_mu(fac) > 0


def test_candidate_set_includes_holdings():
    dossiers = {
        "AAA": {"trends": {"return_3m_pct": 20.0}, "metrics": [{}]},
        "BBB": {"trends": {"return_3m_pct": -5.0}, "metrics": [{}]},
        "ZZZ": {"trends": {"return_3m_pct": 1.0}, "metrics": [{}]},
    }
    deep, ranked = build_candidate_set(["AAA", "BBB", "ZZZ"], dossiers, top_n=1, held={"ZZZ"})
    assert "AAA" in deep
    assert "ZZZ" in deep
    assert ranked[0][0] == "AAA"


def test_agent_overlay_veto_and_boost():
    ranked = [
        ("AAA", 0.5, {}),
        ("BBB", 0.3, {}),
        ("CCC", 0.1, {}),
    ]
    agg = {
        "AAA": {"signal": "bullish", "confidence": 75},
        "BBB": {"signal": "bearish", "confidence": 70},
        "CCC": {"signal": "bullish", "confidence": 80},
    }
    adjusted, vetoed, diag = apply_agent_overlay(ranked, agg)
    assert "BBB" in vetoed
    assert adjusted["AAA"] > 0.5
    assert adjusted["CCC"] == 0.1
    assert diag["vetoes_applied"] == 1


def test_beat_spy_defaults():
    out = apply_beat_spy_defaults({"beat_spy_mode": True, "cash_buffer_pct": 0.12})
    assert out["cash_buffer_pct"] <= 0.05
    assert out["max_stocks"] == 400


def test_scorecard_append(tmp_path, monkeypatch):
    from src.performance import beat_spy_scorecard as mod

    monkeypatch.setattr(mod, "HISTORY_PATH", tmp_path / "hist.jsonl")
    monkeypatch.setattr(mod, "LATEST_JSON", tmp_path / "latest.json")
    monkeypatch.setattr(mod, "LATEST_MD", tmp_path / "latest.md")
    sc = build_beat_spy_scorecard(
        run_date="2026-07-14",
        equity=10000.0,
        benchmark={"equity_delta_pct": 0.5, "spy_return_pct": 0.3, "active_vs_spy_pct": 0.2},
    )
    assert sc["weeks_recorded"] == 1
    assert sc["latest"]["equity"] == 10000.0
