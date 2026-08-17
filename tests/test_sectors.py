"""Sector resolution and concentration-cap helpers."""

from __future__ import annotations

from src.portfolio.sectors import (
    get_sector,
    normalize_sector,
    prefetch_sectors,
    resolve_sector,
)


def test_normalize_yahoo_financial_services():
    assert normalize_sector("Financial Services") == "Financials"
    assert normalize_sector("Information Technology") == "Information Technology"
    assert normalize_sector("Technology") == "Information Technology"
    assert normalize_sector(None) == "Unknown"


def test_static_map_covers_banks():
    assert get_sector("BMO") == "Financials"
    assert get_sector("JPM") == "Financials"
    assert get_sector("AAPL") == "Information Technology"


def test_resolve_sector_uses_dossier_hint(monkeypatch):
    monkeypatch.setattr(
        "src.portfolio.sectors._yahoo_sector",
        lambda t: (_ for _ in ()).throw(AssertionError("should not call yahoo")),
    )
    sec = resolve_sector(
        "FAKECO",
        dossier={"context": {"sector": "Health Care"}},
    )
    assert sec == "Health Care"


def test_prefetch_sectors_batch():
    out = prefetch_sectors(["BMO", "AAPL", "BNS"])
    assert out["BMO"] == "Financials"
    assert out["BNS"] == "Financials"
    assert out["AAPL"] == "Information Technology"


def test_sector_cap_blocks_overweight_financials_buy():
    """Known Financials must respect max_sector_pct (the bug we shipped to fix)."""
    from src.agents.base import AgentSignal
    from src.portfolio.manager import PortfolioManager
    from src.portfolio.models import Portfolio, Position

    pm = PortfolioManager()
    portfolio = Portfolio(cash=5_000.0)
    # ~70% of ~10k equity already in Financials
    portfolio.positions["JPM"] = Position(long=70, long_cost_basis=100.0)

    tickers = ["JPM", "BAC"]
    bull = AgentSignal(signal="bullish", confidence=90, reasoning="x")
    agent_signals = {
        "growth": {"JPM": bull, "BAC": bull},
        "value": {"JPM": bull, "BAC": bull},
    }
    risk_analysis = {
        "JPM": {"remaining_position_limit": 500_000.0, "current_price": 100.0},
        "BAC": {"remaining_position_limit": 500_000.0, "current_price": 50.0},
    }
    dossiers = {
        "JPM": {"context": {"sector": "Financials"}},
        "BAC": {"context": {"sector": "Financials"}},
    }

    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights={"growth": 1.0, "value": 1.0},
        min_buy_confidence=50,
        max_buy_tickers=5,
        max_sector_pct=0.30,
        max_position_pct=0.25,
        enable_covered_calls=False,
        enable_cash_rotation=False,
        ticker_dossiers=dossiers,
    )

    assert decisions["BAC"].action == "hold"
    dd = pm._last_rebalance_diagnostics
    assert int(dd.get("sector_blocks", 0)) >= 1


def test_sector_skip_ahead_fills_buys_from_other_sectors():
    """Overweight Financials must not consume the whole max_buy_tickers budget."""
    from src.agents.base import AgentSignal
    from src.portfolio.manager import PortfolioManager
    from src.portfolio.models import Portfolio, Position

    pm = PortfolioManager()
    portfolio = Portfolio(cash=5_000.0)
    portfolio.positions["JPM"] = Position(long=70, long_cost_basis=100.0)

    tickers = ["JPM", "BAC", "AAPL", "AR"]
    bull = AgentSignal(signal="bullish", confidence=90, reasoning="x")
    agent_signals = {
        "growth": {t: bull for t in tickers},
        "value": {t: bull for t in tickers},
    }
    risk_analysis = {
        "JPM": {"remaining_position_limit": 500_000.0, "current_price": 100.0},
        "BAC": {"remaining_position_limit": 500_000.0, "current_price": 50.0},
        "AAPL": {"remaining_position_limit": 500_000.0, "current_price": 100.0},
        "AR": {"remaining_position_limit": 500_000.0, "current_price": 50.0},
    }
    dossiers = {
        "JPM": {"context": {"sector": "Financials"}},
        "BAC": {"context": {"sector": "Financials"}},
        "AAPL": {"context": {"sector": "Information Technology"}},
        "AR": {"context": {"sector": "Energy"}},
    }

    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk_analysis,
        portfolio=portfolio,
        agent_weights={"growth": 1.0, "value": 1.0},
        min_buy_confidence=50,
        max_buy_tickers=2,
        max_sector_pct=0.30,
        max_position_pct=0.25,
        enable_covered_calls=False,
        enable_cash_rotation=False,
        ticker_dossiers=dossiers,
    )

    buy_tickers = {t for t, d in decisions.items() if d.action == "buy" and d.quantity > 0}
    assert "AAPL" in buy_tickers
    assert "AR" in buy_tickers
    assert "BAC" not in buy_tickers
    dd = pm._last_rebalance_diagnostics
    assert "BAC" in (dd.get("sector_skip_ahead") or [])
    assert int(dd.get("sector_skip_ahead_count", 0)) >= 1
