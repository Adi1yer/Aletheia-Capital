"""Valuation screen tests."""

from src.agents.inputs import AgentInputs
from src.agents.scoring.valuation_screen import score


def test_neutral_without_data():
    inp = AgentInputs("X", "2026-01-01", "2026-05-26", {"version": 2})
    r = score(inp)
    assert r.rule_confidence == 0


def test_bullish_fcf_yield():
    inp = AgentInputs(
        "X",
        "2026-01-01",
        "2026-05-26",
        {
            "version": 2,
            "metrics": [{"pe_ratio": 18, "price_to_book_ratio": 2}],
            "line_items": [{"free_cash_flow": 5e9}],
            "context": {"market_cap": 100e9},
        },
    )
    r = score(inp)
    assert r.suggested_signal in ("bullish", "neutral")
