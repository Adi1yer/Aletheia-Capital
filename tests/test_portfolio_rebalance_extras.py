"""Rebalance extras: cash rotation and covered-call existing lots."""

from __future__ import annotations

from src.agents.base import AgentSignal
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio, Position


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
