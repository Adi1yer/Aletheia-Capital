"""Technicals scorer tests."""

from src.agents.inputs import AgentInputs
from src.agents.scoring.technicals_signals import score


def test_golden_cross_bullish():
    inp = AgentInputs(
        "X",
        "2026-01-01",
        "2026-05-26",
        {
            "version": 2,
            "technicals": {"golden_cross": True, "rsi_14": 55},
            "prices": {"return_pct_period": 10, "return_vs_spy_pct": 3},
        },
    )
    r = score(inp)
    assert r.suggested_signal == "bullish"
