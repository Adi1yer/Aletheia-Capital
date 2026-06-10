"""Short selling in rebalance decisions."""

from src.agents.base import AgentSignal
from src.portfolio.manager import PortfolioManager
from src.portfolio.models import Portfolio


def test_short_allowed_when_bearish():
    pm = PortfolioManager()
    portfolio = Portfolio(cash=50_000)
    tickers = ["XYZ"]
    agent_signals = {
        "a1": {
            "XYZ": AgentSignal(signal="bearish", confidence=80, reasoning="test"),
        }
    }
    risk = {
        "XYZ": {
            "current_price": 100.0,
            "remaining_position_limit": 10_000.0,
        }
    }
    decisions = pm.generate_rebalance_decisions(
        tickers=tickers,
        agent_signals=agent_signals,
        risk_analysis=risk,
        portfolio=portfolio,
        agent_weights={"a1": 1.0},
        min_sell_confidence=60,
        enable_short_selling=True,
        max_short_position_pct=0.05,
        max_short_tickers=3,
    )
    d = decisions.get("XYZ")
    assert d is not None
    assert d.action == "short"
    assert d.quantity > 0
