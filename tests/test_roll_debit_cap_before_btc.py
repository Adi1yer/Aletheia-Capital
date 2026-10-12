"""Test roll debit cap checked BEFORE buyback (CPNG case regression)."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from src.options.wheel_lifecycle import manage_or_roll_short_calls
from src.options.covered_calls import CoveredCallManager


class MockBroker:
    """Mock broker for roll tests."""
    
    def __init__(self):
        self.option_positions = []
        self.account = {"buying_power": 10000.0, "cash": 10000.0}
        self.portfolio_positions = {}
        self.btc_executed = []
        self.sto_executed = []
    
    def get_option_positions(self):
        return self.option_positions
    
    def get_account(self):
        return self.account
    
    def sync_portfolio(self):
        class MockPortfolio:
            def __init__(self, positions):
                self.positions = positions
            
            def long_qty(self, ticker):
                pos = self.positions.get(ticker.upper())
                return pos.get("long", 0) if pos else 0
        
        return MockPortfolio(self.portfolio_positions)
    
    def submit_option_order(self, contract_symbol, qty, side, **kwargs):
        order = {
            "submitted": True,
            "fill_ok": True,
            "order_id": f"{side}-{contract_symbol}",
            "fill": {"ok": True, "filled_avg_price": 0.50 if side == "sell" else 1.50},
            "filled_avg_price": 0.50 if side == "sell" else 1.50,
        }
        
        if side == "buy":
            self.btc_executed.append(contract_symbol)
        elif side == "sell":
            self.sto_executed.append(contract_symbol)
        
        return order


def test_roll_debit_cap_checked_before_btc():
    """Roll debit cap checked BEFORE BTC - reject roll without executing buyback."""
    broker = MockBroker()
    
    # Position: 100 shares of CPNG
    broker.portfolio_positions = {
        "CPNG": {"long": 100}
    }
    
    # Open short call with high mark (expensive to buy back)
    broker.option_positions = [
        {
            "side": "short",
            "symbol": "CPNG261115C00025000",
            "underlying": "CPNG",
            "option_type": "call",
            "strike": 25.0,
            "expiry": "2026-11-15",  # Fixed: was 2024, should be 2026
            "qty": 1,
            "avg_entry_price": 0.50,
            "current_price": 3.00,  # Very high mark - expensive BTC
            "mark_price": 3.00,
        }
    ]
    
    cc_manager = CoveredCallManager()
    
    # Mock select_contract to return a low-premium new call
    def mock_select(underlying, price, score, broker, **kwargs):
        return ({
            "symbol": "CPNG261215C00030000",
            "strike": 30.0,
            "expiry": "2026-12-15",  # Fixed: was 2024
            "estimated_premium_usd": 50.0,  # Low premium
        }, "")
    
    cc_manager.select_contract = mock_select
    
    results = manage_or_roll_short_calls(
        broker=broker,
        current_prices={"CPNG": 26.0},  # Near ITM
        cc_manager=cc_manager,
        manage_dte_threshold=7,
        manage_itm_pct=0.02,
        execute=True,
        prefer_roll=True,
        max_roll_debit_usd=25.0,  # Cap
        max_roll_debit_pct_of_premium=0.25,
    )
    
    # Should reject roll BEFORE BTC
    rejected = [r for r in results if r.get("status") == "roll_rejected_before_btc"]
    assert len(rejected) == 1
    assert "roll_debit_exceeds_cap" in rejected[0]["reason"]
    
    # CRITICAL: BTC should NOT have executed
    assert len(broker.btc_executed) == 0, "BTC should not execute when roll is rejected"
    
    # STO should also not execute
    assert len(broker.sto_executed) == 0


def test_roll_executes_when_debit_cap_passes():
    """Roll proceeds (BTC + STO) when debit cap check passes."""
    broker = MockBroker()
    
    broker.portfolio_positions = {
        "TEST": {"long": 100}
    }
    
    # Short call with reasonable mark
    broker.option_positions = [
        {
            "side": "short",
            "symbol": "TEST261115C00020000",
            "underlying": "TEST",
            "option_type": "call",
            "strike": 20.0,
            "expiry": "2026-11-15",  # Fixed: was 2024, should be 2026
            "qty": 1,
            "avg_entry_price": 1.00,
            "current_price": 0.50,  # Reasonable BTC cost
            "mark_price": 0.50,
        }
    ]
    
    cc_manager = CoveredCallManager()
    
    def mock_select(underlying, price, score, broker, **kwargs):
        return ({
            "symbol": "TEST261215C00025000",
            "strike": 25.0,
            "expiry": "2026-12-15",  # Fixed: was 2024
            "estimated_premium_usd": 80.0,  # Good premium
        }, "")
    
    cc_manager.select_contract = mock_select
    
    results = manage_or_roll_short_calls(
        broker=broker,
        current_prices={"TEST": 19.8},  # Near ITM
        cc_manager=cc_manager,
        manage_dte_threshold=7,
        execute=True,
        prefer_roll=True,
        max_roll_debit_usd=25.0,
    )
    
    # Should execute roll
    executed = [r for r in results if r.get("status") == "roll_executed"]
    assert len(executed) == 1
    
    # Both BTC and STO should have executed
    assert len(broker.btc_executed) == 1
    assert "TEST241115C00020000" in broker.btc_executed[0]
    
    assert len(broker.sto_executed) == 1
    assert "TEST241215C00025000" in broker.sto_executed[0]


def test_simple_btc_executes_without_roll():
    """Simple BTC (no roll) still executes when prefer_roll=False."""
    broker = MockBroker()
    
    broker.portfolio_positions = {
        "NOROLL": {"long": 100}
    }
    
    broker.option_positions = [
        {
            "side": "short",
            "symbol": "NOROLL261115C00020000",
            "underlying": "NOROLL",
            "option_type": "call",
            "strike": 20.0,
            "expiry": "2026-11-15",  # Fixed: was 2024
            "qty": 1,
            "avg_entry_price": 1.00,
            "current_price": 0.20,
            "mark_price": 0.20,
        }
    ]
    
    cc_manager = CoveredCallManager()
    
    results = manage_or_roll_short_calls(
        broker=broker,
        current_prices={"NOROLL": 19.5},
        cc_manager=cc_manager,
        manage_dte_threshold=7,
        execute=True,
        prefer_roll=False,  # No roll, just BTC
    )
    
    # Should execute BTC
    btc = [r for r in results if r.get("status") == "btc_executed"]
    assert len(btc) == 1
    
    # BTC should have executed
    assert len(broker.btc_executed) == 1
    
    # No STO should happen
    assert len(broker.sto_executed) == 0


def test_cpng_case_debit_cap_calculation():
    """CPNG case: verify debit cap calculation is correct."""
    # BTC cost: $300 (3.00 per share × 100)
    # New premium: $50
    # Net credit: $50 - $300 = -$250 (debit)
    # Debit cap: max($25, 25% of $50) = max($25, $12.50) = $25
    # $250 debit > $25 cap → REJECT
    
    btc_cost_per_share = 3.00
    new_prem_per_share = 0.50
    
    btc_cost_full = btc_cost_per_share * 100.0
    new_prem = new_prem_per_share * 100.0
    net_credit = new_prem - btc_cost_full
    
    max_roll_debit_usd = 25.0
    max_roll_debit_pct_of_premium = 0.25
    
    debit_cap = max(
        max_roll_debit_usd * 1,  # 1 contract
        max_roll_debit_pct_of_premium * max(new_prem, 0.0),
    )
    
    assert net_credit == -250.0, f"Expected -$250 debit, got {net_credit}"
    assert debit_cap == 25.0, f"Expected $25 cap, got {debit_cap}"
    assert abs(net_credit) > debit_cap, "Debit should exceed cap"


def test_profit_take_requires_credit():
    """Profit-take rolls must be credit-only (no debit allowed)."""
    broker = MockBroker()
    
    broker.portfolio_positions = {
        "PT": {"long": 100}
    }
    
    # Profit-take scenario: option at 70% profit
    broker.option_positions = [
        {
            "side": "short",
            "symbol": "PT261115C00020000",
            "underlying": "PT",
            "option_type": "call",
            "strike": 20.0,
            "expiry": "2026-11-15",  # Fixed: was 2024
            "qty": 1,
            "avg_entry_price": 1.00,
            "current_price": 0.25,  # 75% profit
            "mark_price": 0.25,
        }
    ]
    
    cc_manager = CoveredCallManager()
    
    def mock_select(underlying, price, score, broker, **kwargs):
        # New call with low premium → small debit after BTC
        return ({
            "symbol": "PT261215C00025000",
            "strike": 25.0,
            "expiry": "2026-12-15",  # Fixed: was 2024
            "estimated_premium_usd": 20.0,  # Low premium
        }, "")
    
    cc_manager.select_contract = mock_select
    
    results = manage_or_roll_short_calls(
        broker=broker,
        current_prices={"PT": 18.0},  # Not near ITM
        cc_manager=cc_manager,
        profit_take_pct=0.60,  # Trigger profit take
        execute=True,
        prefer_roll=True,
    )
    
    # Should reject roll BEFORE BTC (profit-take requires credit)
    rejected = [r for r in results if r.get("status") == "roll_rejected_before_btc"]
    assert len(rejected) >= 1
    
    # Verify reason mentions profit-take
    profit_take_rejects = [
        r for r in rejected 
        if "profit_take_requires_credit" in r.get("reason", "")
    ]
    assert len(profit_take_rejects) >= 1
    
    # BTC should NOT execute
    assert len(broker.btc_executed) == 0
