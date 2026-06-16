"""Rebalance extras: cash rotation and covered-call existing lots."""

from __future__ import annotations

from unittest.mock import patch

from src.agents.base import AgentSignal
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio, Position


def test_aggregate_signals_excludes_neutral_denominator():
    pm = PortfolioManager()
    ticker = "SMCI"
    agent_signals = {
        "growth_analyst": {ticker: AgentSignal(signal="bullish", confidence=90, reasoning="x")},
        "ben_graham": {ticker: AgentSignal(signal="neutral", confidence=0, reasoning="x")},
    }
    out = pm._aggregate_signals(ticker, agent_signals, {"growth_analyst": 1.0, "ben_graham": 1.0})
    assert out["signal"] == "bullish"
    assert out["confidence"] >= 85


def test_cash_rotation_sells_weakest_hold_to_fund_buy():
    pm = PortfolioManager()
    portfolio = Portfolio(cash=0.0)
    portfolio.positions["WEAK"] = Position(long=100, long_cost_basis=1.0)
    portfolio.positions["NEWBUY"] = Position(long=0, long_cost_basis=0.0)

    tickers = ["WEAK", "NEWBUY"]
    agent_signals = {
        "cathie_wood": {
            "WEAK": AgentSignal(signal="bearish", confidence=70, reasoning="x"),
            "NEWBUY": AgentSignal(signal="bullish", confidence=90, reasoning="x"),
        },
        "warren_buffett": {
            "WEAK": AgentSignal(signal="bearish", confidence=70, reasoning="x"),
            "NEWBUY": AgentSignal(signal="bullish", confidence=90, reasoning="x"),
        },
    }
    agent_weights = {"cathie_wood": 1.0, "warren_buffett": 1.0}
    risk_analysis = {
        "WEAK": {"remaining_position_limit": 500_000.0, "current_price": 10.0},
        "NEWBUY": {"remaining_position_limit": 500_000.0, "current_price": 10.0},
    }

    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights=agent_weights,
        pending_orders_by_symbol={},
        min_buy_confidence=50,
        min_sell_confidence=75,
        cash_buffer_pct=0.05,
        max_buy_tickers=20,
        enable_covered_calls=False,
        enable_conviction_rebalance=False,
        enable_cash_rotation=True,
        cash_rotation_min_edge=5,
    )

    assert decisions["WEAK"].action == "sell"
    assert "Cash rotation" in (decisions["WEAK"].reasoning or "")
    assert decisions["NEWBUY"].action == "buy"
    assert decisions["NEWBUY"].quantity >= 1
    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("cash_rotation_sell_count", 0)) >= 1


def test_cash_rotation_skipped_when_edge_insufficient():
    pm = PortfolioManager()
    portfolio = Portfolio(cash=0.0)
    portfolio.positions["OLD"] = Position(long=100, long_cost_basis=1.0)

    tickers = ["OLD", "NEWBUY"]
    agent_signals = {
        "cathie_wood": {
            "OLD": AgentSignal(signal="bullish", confidence=88, reasoning="x"),
            "NEWBUY": AgentSignal(signal="bullish", confidence=90, reasoning="x"),
        },
        "warren_buffett": {
            "OLD": AgentSignal(signal="bullish", confidence=88, reasoning="x"),
            "NEWBUY": AgentSignal(signal="bullish", confidence=90, reasoning="x"),
        },
    }
    agent_weights = {"cathie_wood": 1.0, "warren_buffett": 1.0}
    risk_analysis = {
        "OLD": {"remaining_position_limit": 500_000.0, "current_price": 10.0},
        "NEWBUY": {"remaining_position_limit": 500_000.0, "current_price": 10.0},
    }

    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights=agent_weights,
        pending_orders_by_symbol={},
        min_buy_confidence=50,
        min_sell_confidence=60,
        cash_buffer_pct=0.05,
        max_buy_tickers=1,
        enable_covered_calls=False,
        enable_conviction_rebalance=False,
        enable_cash_rotation=True,
        cash_rotation_min_edge=5,
    )

    assert decisions["OLD"].action != "sell"
    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("cash_rotation_skipped_edge", 0)) >= 1


def test_cc_existing_long_round_lot_without_cash_budget():
    pm = PortfolioManager()
    portfolio = Portfolio(cash=0.0)
    portfolio.positions["CCONLY"] = Position(long=120, long_cost_basis=1.0)

    tickers = ["CCONLY"]
    agent_signals = {
        "cathie_wood": {
            "CCONLY": AgentSignal(signal="bullish", confidence=60, reasoning="x"),
        },
        "warren_buffett": {
            "CCONLY": AgentSignal(signal="bearish", confidence=60, reasoning="x"),
        },
    }
    agent_weights = {"cathie_wood": 1.0, "warren_buffett": 1.0}
    risk_analysis = {
        "CCONLY": {"remaining_position_limit": 500_000.0, "current_price": 50.0},
    }

    pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights=agent_weights,
        pending_orders_by_symbol={},
        min_buy_confidence=80,
        min_sell_confidence=60,
        cash_buffer_pct=0.05,
        max_buy_tickers=20,
        enable_covered_calls=True,
        min_cc_score=40,
        enable_conviction_rebalance=False,
        enable_cash_rotation=False,
    )

    assert pm._last_cc_lot_tickers == ["CCONLY"]
    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("cc_held_lot_count", 0)) >= 1


def test_cash_rotation_when_buys_not_meaningfully_allocatable():
    """Rotation should sell a weak hold when top buys cannot meet min notional (not one cheap share)."""
    pm = PortfolioManager()
    portfolio = Portfolio(cash=2000.0)
    portfolio.positions["WEAK"] = Position(long=50, long_cost_basis=5.0)

    tickers = ["WEAK", "EXP"]
    agent_signals = {
        "growth": {
            "WEAK": AgentSignal(signal="bearish", confidence=70, reasoning="x"),
            "EXP": AgentSignal(signal="bullish", confidence=95, reasoning="x"),
        },
        "value": {
            "WEAK": AgentSignal(signal="bearish", confidence=70, reasoning="x"),
            "EXP": AgentSignal(signal="bullish", confidence=95, reasoning="x"),
        },
    }
    agent_weights = {"growth": 1.0, "value": 1.0}
    risk_analysis = {
        "WEAK": {"remaining_position_limit": 500_000.0, "current_price": 10.0},
        "EXP": {"remaining_position_limit": 500_000.0, "current_price": 2500.0},
    }

    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights=agent_weights,
        pending_orders_by_symbol={},
        min_buy_confidence=50,
        min_sell_confidence=75,
        cash_buffer_pct=0.03,
        max_buy_tickers=20,
        enable_covered_calls=False,
        enable_cash_rotation=True,
        cash_rotation_min_edge=5,
        cash_rotation_min_buy_notional_usd=1500.0,
        cash_rotation_min_buy_notional_pct_equity=0.02,
    )

    assert decisions["WEAK"].action == "sell"
    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("cash_rotation_sell_count", 0)) >= 1


def test_max_cash_rotation_sells_cap():
    pm = PortfolioManager()
    portfolio = Portfolio(cash=0.0)
    for sym in ("W1", "W2", "W3", "W4"):
        portfolio.positions[sym] = Position(long=100, long_cost_basis=1.0)

    tickers = ["W1", "W2", "W3", "W4", "NEWBUY"]
    weak_sigs = {
        s: AgentSignal(signal="bearish", confidence=70, reasoning="x") for s in ("W1", "W2", "W3", "W4")
    }
    weak_sigs["NEWBUY"] = AgentSignal(signal="bullish", confidence=95, reasoning="x")
    agent_signals = {"growth": weak_sigs, "value": dict(weak_sigs)}
    agent_weights = {"growth": 1.0, "value": 1.0}
    risk_analysis = {s: {"remaining_position_limit": 500_000.0, "current_price": 10.0} for s in tickers}

    pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights=agent_weights,
        pending_orders_by_symbol={},
        min_buy_confidence=50,
        min_sell_confidence=75,
        cash_buffer_pct=0.05,
        max_buy_tickers=20,
        enable_covered_calls=False,
        enable_conviction_rebalance=False,
        enable_cash_rotation=True,
        cash_rotation_min_edge=5,
        max_cash_rotation_sells=2,
    )

    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("cash_rotation_sell_count", 0)) <= 2
    assert dd.get("cash_rotation_skip_reason") == "max_rotation_sells_reached"


def test_csp_economics_filter_skips_low_premium():
    pm = PortfolioManager()
    assert pm._csp_passes_economics(
        price=100.0,
        csp_score=50,
        min_premium_usd=75.0,
        min_annualized_yield_pct=3.0,
    ) is False

    portfolio = Portfolio(cash=50_000.0)
    tickers = ["PPG"]
    agent_signals = {
        "growth": {"PPG": AgentSignal(signal="neutral", confidence=50, reasoning="x")},
        "value": {"PPG": AgentSignal(signal="neutral", confidence=50, reasoning="x")},
    }
    agent_weights = {"growth": 1.0, "value": 1.0}
    risk_analysis = {
        "PPG": {"remaining_position_limit": 500_000.0, "current_price": 100.0},
    }

    with patch.object(
        pm,
        "_score_cash_secured_put",
        return_value=55,
    ):
        pm.generate_rebalance_decisions(
            tickers=tickers,
            agent_signals=agent_signals,
            risk_analysis=risk_analysis,
            portfolio=portfolio,
            agent_weights=agent_weights,
            pending_orders_by_symbol={},
            min_buy_confidence=90,
            min_sell_confidence=90,
            cash_buffer_pct=0.05,
            max_buy_tickers=20,
            enable_covered_calls=False,
            enable_cash_secured_puts=True,
            min_csp_score=40,
            min_csp_premium_usd=75.0,
            min_csp_annualized_yield_pct=3.0,
            enable_cash_rotation=False,
        )

    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("csp_skipped_economics", 0)) >= 1
    assert pm._last_csp_tickers == []


