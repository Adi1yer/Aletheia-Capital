from __future__ import annotations

from src.agents.base import AgentSignal
from src.agents.lane_ensemble import build_lane_signals


def test_lane_ensemble_sparse_and_neutral():
    ticker = "AAPL"
    signals = {
        "growth_analyst": {ticker: AgentSignal(signal="bullish", confidence=80, reasoning="g")},
        "ben_graham": {ticker: AgentSignal(signal="neutral", confidence=0, reasoning="v")},
    }
    out = build_lane_signals(ticker, signals, {"growth_analyst": 1.0, "ben_graham": 1.0})
    assert "lane:growth" in out
    assert out["lane:growth"]["signal"] == "bullish"
    assert out["lane:growth"]["confidence"] >= 75
    assert "lane:value" not in out


def test_lane_ensemble_mixed_weights():
    ticker = "MSFT"
    signals = {
        "growth_analyst": {ticker: AgentSignal(signal="bullish", confidence=60, reasoning="a")},
        "cathie_wood": {ticker: AgentSignal(signal="bearish", confidence=90, reasoning="b")},
    }
    out = build_lane_signals(ticker, signals, {"growth_analyst": 1.0, "cathie_wood": 0.1})
    assert out["lane:growth"]["signal"] == "bullish"
