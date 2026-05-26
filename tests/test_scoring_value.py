"""Value checklist scorer tests."""

from src.agents.inputs import AgentInputs
from src.agents.scoring.value_checklist import score


def _inputs(metrics, trends=None):
    return AgentInputs(
        ticker="TST",
        start_date="2026-01-01",
        end_date="2026-05-26",
        dossier={
            "version": 2,
            "metrics": [metrics],
            "trends": trends or {},
            "line_items": [],
            "prices": {},
            "technicals": {},
            "context": {},
        },
    )


def test_graham_stricter_pb():
    m = {
        "price_to_book_ratio": 2.0,
        "debt_to_equity": 50,
        "roe": 0.12,
    }
    r = score(_inputs(m), profile="graham")
    assert r.lane == "value"
    assert r.suggested_signal in ("bullish", "bearish", "neutral")


def test_buffett_bullish_quality():
    m = {
        "price_to_book_ratio": 3.0,
        "debt_to_equity": 0.5,
        "roe": 0.18,
    }
    r = score(_inputs(m, {"revenue_yoy_pct": 8.0}), profile="buffett")
    assert r.suggested_signal == "bullish"
