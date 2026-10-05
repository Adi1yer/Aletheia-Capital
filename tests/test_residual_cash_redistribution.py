"""Unit test for residual cash redistribution fix (Oct 5 2026 CI failure)."""

from unittest.mock import MagicMock
import pytest


class FakeBroker:
    """Minimal fake broker for testing deploy_residual_cash."""
    
    def __init__(self, prices=None):
        self.prices = prices or {}
        self.orders_submitted = []
    
    def get_last_equity_prices(self, symbols):
        return {s: self.prices.get(s, 0) for s in symbols if s in self.prices}
    
    def execute_order(self, ticker, decision, current_price=None):
        self.orders_submitted.append({
            "ticker": ticker,
            "action": decision.action,
            "quantity": decision.quantity,
            "current_price": current_price,
        })
        return {
            "success": True,
            "order_id": f"test_order_{len(self.orders_submitted)}",
        }


def test_residual_cash_redistribution_with_zero_initial_shares():
    """Test that redistribution works for tickers starting with 0 shares.
    
    This was the bug that caused CI failure on 997a249:
    - AAPL @ $300: gets $200 allocation → 0 shares, $200 leftover
    - MSFT @ $300: gets $200 allocation → 0 shares, $200 leftover
    - Total leftover: $400
    - Redistribution should give AAPL 1 share ($300) since gap=$100 and leftover=$400
    """
    from scripts.growth_income_drip_rebalance import deploy_residual_cash
    
    current_positions = {
        "AAPL": {"qty": 10, "market_value": 5000.0},  # 50%
        "MSFT": {"qty": 5, "market_value": 5000.0},   # 50%
    }
    
    broker = FakeBroker(prices={"AAPL": 300.0, "MSFT": 300.0})
    
    actions = deploy_residual_cash(broker, current_positions, 400.0, min_trade_usd=100.0)
    
    # With the fix, should buy 1 share of AAPL ($300 from $400 leftover pool)
    assert len(actions["buys"]) == 1, f"Expected 1 buy after redistribution, got {len(actions['buys'])}"
    
    buy = actions["buys"][0]
    assert buy["ticker"] == "AAPL"
    assert buy["shares"] == 1
    assert buy["allocated_usd"] == 300.0


def test_residual_cash_redistribution_with_nonzero_initial_shares():
    """Test that redistribution still works for tickers with initial shares."""
    from scripts.growth_income_drip_rebalance import deploy_residual_cash
    
    current_positions = {
        "AAPL": {"qty": 10, "market_value": 3000.0},  # 60%
        "MSFT": {"qty": 5, "market_value": 2000.0},   # 40%
    }
    
    # AAPL @ $150: 60% of $500 = $300 → 2 shares @ $150 = $300, $0 leftover
    # MSFT @ $250: 40% of $500 = $200 → 0 shares @ $250, $200 leftover
    # Total leftover: $200. Can buy 1 more AAPL share ($150) from leftover.
    broker = FakeBroker(prices={"AAPL": 150.0, "MSFT": 250.0})
    
    actions = deploy_residual_cash(broker, current_positions, 500.0, min_trade_usd=50.0)
    
    assert len(actions["buys"]) >= 1
    
    aapl_orders = [b for b in actions["buys"] if b["ticker"] == "AAPL"]
    assert len(aapl_orders) == 1
    
    # AAPL should have base 2 shares + 1 redistributed = 3 shares, $450 total
    aapl_order = aapl_orders[0]
    assert aapl_order["shares"] == 3
    assert aapl_order["allocated_usd"] == 450.0


def test_residual_cash_redistribution_sorts_by_gap():
    """Test that redistribution prioritizes tickers closest to affording a share."""
    from scripts.growth_income_drip_rebalance import deploy_residual_cash
    
    current_positions = {
        "AAPL": {"qty": 10, "market_value": 4000.0},  # 40%
        "MSFT": {"qty": 5, "market_value": 3000.0},   # 30%
        "GOOGL": {"qty": 2, "market_value": 3000.0},  # 30%
    }
    
    # AAPL @ $100: 40% of $1000 = $400 → 4 shares, $0 leftover, gap=$100
    # MSFT @ $200: 30% of $1000 = $300 → 1 share @ $200, $100 leftover, gap=$100
    # GOOGL @ $350: 30% of $1000 = $300 → 0 shares, $300 leftover, gap=$50
    # Total leftover: $400
    # Redistribution order: GOOGL (gap $50), then AAPL/MSFT (gap $100)
    # GOOGL gets 1 share ($350), leaving $50 (not enough for AAPL/MSFT)
    broker = FakeBroker(prices={"AAPL": 100.0, "MSFT": 200.0, "GOOGL": 350.0})
    
    actions = deploy_residual_cash(broker, current_positions, 1000.0, min_trade_usd=50.0)
    
    # Should have orders for AAPL (4 shares), MSFT (1 share), GOOGL (1 share redistributed)
    assert len(actions["buys"]) == 3
    
    googl_order = next((b for b in actions["buys"] if b["ticker"] == "GOOGL"), None)
    assert googl_order is not None
    assert googl_order["shares"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
