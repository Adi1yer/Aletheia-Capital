"""Phase 13 profitability policy unit tests."""

from __future__ import annotations

from src.portfolio.phase13_policy import (
    apply_phase13_defaults,
    filter_buys_for_risk_off,
    is_special_opportunity,
    position_stop_triggered,
    resolve_cash_buffer_pct,
)
from src.portfolio.net_edge import net_edge_score
from src.biotech.readout_window import is_ghost_catalyst
from src.biotech.models import TrialSummary
from datetime import date, timedelta


def test_cash_buffer_risk_off():
    assert resolve_cash_buffer_pct(regime_mode="neutral") >= 0.12
    assert resolve_cash_buffer_pct(regime_mode="harvest") >= 0.20


def test_special_opportunity_bar():
    assert is_special_opportunity(90, net_edge=1.0, top_edge=1.0)
    assert not is_special_opportunity(70, net_edge=1.0, top_edge=1.0)


def test_risk_off_filters_ordinary_buys():
    cands = [("AAA", 70), ("BBB", 90), ("CCC", 88)]
    edges = {"AAA": 0.2, "BBB": 1.0, "CCC": 0.95}
    kept, tags = filter_buys_for_risk_off(cands, net_edges=edges, risk_off=True, allow_special=True)
    assert all(t in ("BBB", "CCC") for t, _ in kept)
    assert "AAA" not in tags


def test_book_stop():
    assert position_stop_triggered(qty=10, price=90.0, cost_basis=100.0, stop_pct=0.08)
    assert not position_stop_triggered(qty=10, price=95.0, cost_basis=100.0, stop_pct=0.08)


def test_phase13_defaults_tighten_knobs():
    out = apply_phase13_defaults(
        {
            "min_buy_confidence": 49,
            "min_sell_confidence": 60,
            "cash_buffer_pct": 0.03,
            "max_buy_tickers": 30,
            "max_position_pct": 0.20,
        }
    )
    assert out["min_buy_confidence"] >= 65
    assert out["min_sell_confidence"] <= 55
    assert out["cash_buffer_pct"] >= 0.12
    assert out["max_buy_tickers"] <= 8
    assert out["max_position_pct"] <= 0.07


def test_net_edge_positive_with_confidence():
    assert net_edge_score(confidence=80, agent_details=[], scorecard={}) > 0


def test_ghost_catalyst():
    past = (date.today() - timedelta(days=10)).isoformat()
    ghost = TrialSummary(nct_id="NCT1", primary_completion_date=past, has_results=False)
    assert is_ghost_catalyst(ghost, date.today())
    live = TrialSummary(
        nct_id="NCT2",
        primary_completion_date=past,
        has_results=True,
        results_first_posted=past,
    )
    assert not is_ghost_catalyst(live, date.today())
