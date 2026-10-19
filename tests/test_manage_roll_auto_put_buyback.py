"""Tests that manage_or_roll honors AUTO_PUT_BUYBACK flag for put BTC."""

from __future__ import annotations

import pytest

from src.options.covered_calls import CoveredCallManager
from src.options.wheel_lifecycle import manage_or_roll_short_calls
from src.portfolio.models import Portfolio, Position


class MockBroker:
    """Mock broker for AUTO_PUT_BUYBACK control tests."""

    def __init__(
        self,
        option_positions=None,
        submit_success=True,
        has_shares=False,
    ):
        self.option_positions = option_positions or []
        self.submit_success = submit_success
        self.has_shares = has_shares
        self.submitted_orders = []

    def get_option_positions(self):
        return self.option_positions

    def get_option_contracts(self, **kwargs):
        return [
            {
                "symbol": "NU261106C00015000",
                "strike": 15.0,
                "expiry": "2026-11-06",
                "tradable": True,
                "mid_price": 0.30,
            }
        ]

    def submit_option_order(self, **kwargs):
        self.submitted_orders.append(kwargs)
        if self.submit_success:
            return {
                "submitted": True,
                "fill_ok": True,
                "order_id": f"test-{len(self.submitted_orders)}",
                "fill": {"ok": True, "filled_avg_price": 0.25},
            }
        else:
            return {"submitted": False, "fill_ok": False}

    def sync_portfolio(self):
        if self.has_shares:
            return Portfolio(
                cash=5000.0,
                positions={"NU": Position(long=100, long_cost_basis=14.50)},
            )
        return Portfolio(cash=5000.0, positions={})


def test_manage_or_roll_skips_put_btc_when_auto_put_buyback_false():
    """When AUTO_PUT_BUYBACK=0, near-ITM puts should be skipped (not BTC)."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.80,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.10,
        target_otm_pct=0.05,
    )

    # Execute with auto_put_buyback=False (default)
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},  # Underlying near strike $15 → put_near_itm
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=True,
        auto_put_buyback=False,
    )

    # Verify no BTC order was submitted
    assert len(broker.submitted_orders) == 0

    # Verify put was skipped with correct status
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "skipped"
    assert "AUTO_PUT_BUYBACK=0" in put_results[0]["reason"]
    assert "put_near_itm" in put_results[0]["reason"]


def test_manage_or_roll_executes_put_btc_when_auto_put_buyback_true():
    """When AUTO_PUT_BUYBACK=1, near-ITM puts should be bought to close."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.80,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.10,
        target_otm_pct=0.05,
    )

    # Execute with auto_put_buyback=True
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},  # Underlying near strike $15 → put_near_itm
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=True,
        auto_put_buyback=True,
    )

    # Verify BTC order was submitted
    assert len(broker.submitted_orders) == 1
    order = broker.submitted_orders[0]
    assert order["contract_symbol"] == "NU261106P00015000"
    assert order["side"] == "buy"
    assert order["qty"] == 1

    # Verify put was executed
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "btc_executed"


def test_manage_or_roll_calls_unaffected_by_auto_put_buyback_flag():
    """Call BTC/roll should work regardless of AUTO_PUT_BUYBACK setting."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106C00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.50,
                "current_price": 0.80,
            }
        ],
        submit_success=True,
        has_shares=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.10,
        target_otm_pct=0.05,
    )

    # Execute with auto_put_buyback=False (calls should still work)
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 15.25},  # Underlying near strike → call_near_itm
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=True,
        auto_put_buyback=False,
    )

    # Verify BTC order was submitted for call
    btc_orders = [o for o in broker.submitted_orders if o["side"] == "buy"]
    assert len(btc_orders) >= 1

    # Verify call was processed (not skipped)
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) > 0
    assert not any(r.get("status") == "skipped" for r in call_results)


def test_manage_or_roll_multiple_puts_all_skipped_when_flag_off():
    """When AUTO_PUT_BUYBACK=0, all put BTC should be skipped."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.80,
            },
            {
                "symbol": "CPNG261030P00016500",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.70,
                "current_price": 0.20,
            },
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
        otm_pct_low=0.03,
        otm_pct_high=0.10,
        target_otm_pct=0.05,
    )

    # Execute with auto_put_buyback=False
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70, "CPNG": 16.20},
        mgr,
        manage_dte_threshold=7,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
        prefer_roll=True,
        execute=True,
        auto_put_buyback=False,
    )

    # Verify no BTC orders submitted
    assert len(broker.submitted_orders) == 0

    # Verify all puts were skipped
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) >= 2
    for r in put_results:
        assert r["status"] == "skipped"
        assert "AUTO_PUT_BUYBACK=0" in r["reason"]


def test_manage_or_roll_dry_run_skips_put_btc_when_flag_off():
    """Dry-run mode should also respect AUTO_PUT_BUYBACK flag."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.80,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    # Dry-run with auto_put_buyback=False
    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},
        mgr,
        manage_itm_pct=0.02,
        prefer_roll=True,
        execute=False,  # Dry run
        auto_put_buyback=False,
    )

    # Verify no orders submitted (dry run)
    assert len(broker.submitted_orders) == 0

    # Verify put shows skipped, not would_btc
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "skipped"
    assert "allow_put_closes=False_blocked" in put_results[0]["reason"]


def test_prefer_roll_false_blocks_put_btc_when_auto_put_buyback_false():
    """With prefer_roll=False + execute=True, put BTC must be blocked before submission."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.20,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},
        mgr,
        manage_dte_threshold=7,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
        prefer_roll=False,
        execute=True,
        auto_put_buyback=False,
    )

    assert len(broker.submitted_orders) == 0
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "skipped"
    assert "allow_put_closes=False_blocked" in put_results[0]["reason"]


def test_prefer_roll_false_executes_put_btc_when_auto_put_buyback_true():
    """With prefer_roll=False + execute=True, put BTC submits when auto_put_buyback=True."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106P00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.60,
                "current_price": 0.20,
            }
        ],
        submit_success=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    results = manage_or_roll_short_calls(
        broker,
        {"NU": 14.70},
        mgr,
        manage_dte_threshold=7,
        manage_itm_pct=0.02,
        profit_take_pct=0.60,
        prefer_roll=False,
        execute=True,
        auto_put_buyback=True,
    )

    assert len(broker.submitted_orders) == 1
    order = broker.submitted_orders[0]
    assert order["contract_symbol"] == "NU261106P00015000"
    assert order["side"] == "buy"
    assert order["qty"] == 1

    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "btc_executed"
