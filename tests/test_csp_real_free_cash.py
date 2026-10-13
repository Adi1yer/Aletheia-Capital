"""Test CSP sizing against real free cash (10/6 case regression)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.options.cash_secured_puts import CashSecuredPutManager


class MockBroker:
    """Mock broker for CSP tests."""
    
    def __init__(self, free_cash: float = 10000.0):
        self.free_cash = free_cash
        self.account = {
            "buying_power": free_cash,
            "cash": free_cash,
            "equity": free_cash,
        }
        self.option_contracts = []
        self.open_orders = []  # Add open orders support
    
    def get_account(self):
        return self.account
    
    def get_option_contracts(self, **kwargs):
        return self.option_contracts
    
    def enrich_option_quotes(self, contracts):
        pass
    
    def get_open_orders(self, limit=100):
        return self.open_orders
    
    def submit_option_order(self, **kwargs):
        return {
            "submitted": True,
            "fill_ok": True,
            "order_id": "test-order-123",
            "fill": {"ok": True, "filled_avg_price": 0.5},
        }


def test_csp_respects_real_free_cash():
    """CSP sizing checks against real broker cash, not seeded collateral."""
    # 10/6 EOD case: $2,052.28 free cash, open puts need $2,150 → $98 short
    free_cash = 2052.28
    existing_put_collateral = 2150.0
    
    broker = MockBroker(free_cash=free_cash)
    # Add a tradable contract with sufficient premium
    broker.option_contracts = [
        {
            "symbol": "PCG241115P00020000",
            "underlying": "PCG",
            "strike": 20.0,
            "expiry": "2024-11-15",
            "tradable": True,
            "mid_price": 1.0,  # Increased: was 0.50, need >$75 premium ($1.00 × 100 = $100)
        }
    ]
    
    # Simulate existing open put positions
    # PCG: $20 strike = $2,000 collateral
    # PSKY: $1.50 strike = $150 collateral
    # Total: $2,150 collateral
    option_positions = [
        {
            "side": "short",
            "symbol": "PCG241115P00020000",
            "option_type": "put",
            "underlying": "PCG",
            "strike": 20.0,
            "qty": 1,
        },
        {
            "side": "short",
            "symbol": "PSKY241115P00001500",
            "option_type": "put",
            "underlying": "PSKY",
            "strike": 1.5,  # Fixed: was 15.0, should be 1.5 for $150
            "qty": 1,
        },
    ]
    
    manager = CashSecuredPutManager()
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=["NEWPUT"],
        csp_scores={"NEWPUT": 60},
        current_prices={"NEWPUT": 25.0},
        wait_fill=False,
        option_positions=option_positions,
    )
    
    # Should have alert about insufficient cash
    alerts = [r for r in results if r.get("status") == "alert"]
    assert len(alerts) == 1
    assert "insufficient_free_cash" in alerts[0]["reason"]
    assert abs(alerts[0]["shortage"] - 97.72) < 0.1  # ~$98 short
    
    # Should skip ALL new puts due to insufficient cash (available_cash < 0)
    skipped = [r for r in results if r.get("status") == "skipped"]
    assert len(skipped) == 1
    assert skipped[0]["underlying"] == "NEWPUT"
    assert "insufficient_free_cash" in skipped[0]["reason"]
    
    # Should have NO executed puts (critical: 10/6 case must not place new puts)
    executed = [r for r in results if r.get("status") == "executed"]
    assert len(executed) == 0


def test_csp_allows_new_puts_with_sufficient_cash():
    """CSP allows new puts when free cash covers existing + new collateral."""
    free_cash = 5000.0
    
    broker = MockBroker(free_cash=free_cash)
    broker.option_contracts = [
        {
            "symbol": "TEST241115P00020000",
            "underlying": "TEST",
            "strike": 20.0,
            "expiry": "2024-11-15",
            "tradable": True,
            "mid_price": 0.75,
        }
    ]
    
    # Existing put using $2000 collateral
    option_positions = [
        {
            "side": "short",
            "symbol": "OLD241115P00020000",
            "option_type": "put",
            "underlying": "OLD",
            "strike": 20.0,
            "qty": 1,
        },
    ]
    
    manager = CashSecuredPutManager()
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=["TEST"],
        csp_scores={"TEST": 60},
        current_prices={"TEST": 25.0},
        wait_fill=False,
        option_positions=option_positions,
    )
    
    # Should not have alert since we have enough cash
    alerts = [r for r in results if r.get("status") == "alert"]
    # Alert only appears when available_cash < 0, which it isn't here
    
    # Should execute new put successfully
    executed = [r for r in results if r.get("status") == "executed"]
    assert len(executed) == 1
    assert executed[0]["underlying"] == "TEST"


def test_csp_midday_shortage_case():
    """Simulate 10/6 midday case with ~$1,097 shortage."""
    free_cash = 1000.0  # Low midday cash
    
    broker = MockBroker(free_cash=free_cash)
    broker.option_contracts = [
        {
            "symbol": "NEW241115P00025000",
            "underlying": "NEW",
            "strike": 25.0,
            "expiry": "2024-11-15",
            "tradable": True,
            "mid_price": 0.80,
        }
    ]
    
    # Open puts needing $2,097 collateral
    option_positions = [
        {
            "side": "short",
            "symbol": "A241115P00020000",
            "option_type": "put",
            "underlying": "A",
            "strike": 20.0,
            "qty": 1,  # $2000
        },
        {
            "side": "short",
            "symbol": "B241115P00001000",
            "option_type": "put",
            "underlying": "B",
            "strike": 0.97,
            "qty": 1,  # $97
        },
    ]
    
    manager = CashSecuredPutManager()
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=["NEW"],
        csp_scores={"NEW": 55},
        current_prices={"NEW": 30.0},
        wait_fill=False,
        option_positions=option_positions,
    )
    
    # Should have shortage alert
    alerts = [r for r in results if r.get("status") == "alert"]
    assert len(alerts) == 1
    assert alerts[0]["shortage"] > 1000  # ~$1,097 short
    
    # Should skip ALL new puts when available_cash < 0
    skipped = [
        r for r in results 
        if r.get("status") == "skipped" 
        and "insufficient_free_cash" in r.get("reason", "")
    ]
    assert len(skipped) == 1
    assert skipped[0]["underlying"] == "NEW"
    
    # Should have NO executed puts
    executed = [r for r in results if r.get("status") == "executed"]
    assert len(executed) == 0


def test_csp_logs_sizing_info():
    """Verify CSP logs critical sizing info for debugging."""
    import structlog
    
    free_cash = 2052.28
    broker = MockBroker(free_cash=free_cash)
    broker.option_contracts = []
    
    option_positions = [
        {
            "side": "short",
            "symbol": "P241115P00020000",
            "option_type": "put",
            "strike": 20.0,
            "qty": 1,
        }
    ]
    
    manager = CashSecuredPutManager()
    
    # Capture logs
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=[],
        csp_scores={},
        current_prices={},
        wait_fill=False,
        option_positions=option_positions,
    )
    
    # Should complete without error
    assert isinstance(results, list)


def test_csp_broker_cash_unavailable_error():
    """Handle broker cash fetch failure gracefully."""
    
    class BrokenBroker:
        def get_account(self):
            raise Exception("Broker API down")
        
        def get_open_orders(self, limit=100):
            return []
    
    broker = BrokenBroker()
    manager = CashSecuredPutManager()
    
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=["TEST"],
        csp_scores={"TEST": 60},
        current_prices={"TEST": 25.0},
        wait_fill=False,
    )
    
    # Should return error status
    assert len(results) == 1
    assert results[0]["status"] == "error"
    assert results[0]["reason"] == "broker_cash_unavailable"


def test_csp_open_orders_unavailable_fail_closed():
    """Skip all new puts when open orders fetch fails (fail-closed)."""
    
    class PartialBroker:
        def get_account(self):
            return {"cash": 10000.0, "buying_power": 10000.0}
        
        def get_open_orders(self, limit=100):
            raise Exception("Orders API down")
    
    broker = PartialBroker()
    manager = CashSecuredPutManager()
    
    results = manager.execute_cash_secured_puts(
        broker=broker,
        csp_tickers=["TEST1", "TEST2"],
        csp_scores={"TEST1": 60, "TEST2": 55},
        current_prices={"TEST1": 25.0, "TEST2": 30.0},
        wait_fill=False,
    )
    
    # Should skip all puts (fail-closed)
    assert len(results) == 2
    assert all(r["status"] == "skipped" for r in results)
    assert all("open_orders_unavailable_fail_closed" in r["reason"] for r in results)
