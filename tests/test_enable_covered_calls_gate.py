"""Tests that ENABLE_COVERED_CALLS gate blocks all call roll orders."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from src.options.covered_calls import CoveredCallManager
from src.options.wheel_lifecycle import manage_or_roll_short_calls


class MockBroker:
    """Mock broker for ENABLE_COVERED_CALLS gate tests."""

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
        from src.portfolio.models import Portfolio, Position
        if self.has_shares:
            return Portfolio(
                cash=5000.0,
                positions={"NU": Position(long=100, long_cost_basis=14.50)},
            )
        return Portfolio(cash=5000.0, positions={})


def test_enable_covered_calls_off_blocks_call_btc_prefer_roll_true():
    """When ENABLE_COVERED_CALLS=0 + prefer_roll=True, call BTC must be blocked."""
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

    # Set ENABLE_COVERED_CALLS=0
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "0"
        
        results = manage_or_roll_short_calls(
            broker,
            {"NU": 15.25},  # Near strike → call_near_itm
            mgr,
            manage_itm_pct=0.02,
            prefer_roll=True,
            execute=True,
            auto_put_buyback=False,
        )
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify NO orders submitted
    assert len(broker.submitted_orders) == 0

    # Verify call was skipped
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) >= 1
    for r in call_results:
        assert r.get("status") == "skipped"
        assert "allow_call_closes=False_blocked" in r.get("reason", "")


def test_enable_covered_calls_on_allows_call_btc_prefer_roll_true():
    """When ENABLE_COVERED_CALLS=1 + prefer_roll=True, call BTC proceeds normally."""
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

    # Set ENABLE_COVERED_CALLS=1
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        results = manage_or_roll_short_calls(
            broker,
            {"NU": 15.25},  # Near strike → call_near_itm
            mgr,
            manage_itm_pct=0.02,
            prefer_roll=True,
            execute=True,
            auto_put_buyback=False,
        )
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify BTC order WAS submitted
    btc_orders = [o for o in broker.submitted_orders if o.get("side") == "buy"]
    assert len(btc_orders) >= 1
    assert btc_orders[0]["contract_symbol"] == "NU261106C00015000"

    # Verify call was processed (not skipped due to gate)
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) >= 1
    # Should have btc_executed or roll statuses, not skipped due to gate
    for r in call_results:
        assert "allow_call_closes=False_blocked" not in r.get("reason", "")


def test_enable_covered_calls_off_blocks_call_btc_prefer_roll_false():
    """When ENABLE_COVERED_CALLS=0 + prefer_roll=False, call BTC must be blocked."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106C00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.50,
                "current_price": 0.20,
            }
        ],
        submit_success=True,
        has_shares=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    # Set ENABLE_COVERED_CALLS=0
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "0"
        
        results = manage_or_roll_short_calls(
            broker,
            {"NU": 15.25},
            mgr,
            manage_dte_threshold=7,
            manage_itm_pct=0.02,
            profit_take_pct=0.60,
            prefer_roll=False,
            execute=True,
            auto_put_buyback=False,
        )
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify NO orders submitted
    assert len(broker.submitted_orders) == 0

    # Verify call was skipped
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) >= 1, "Expected at least one call result"
    for r in call_results:
        assert r.get("status") == "skipped"
        assert "allow_call_closes=False_blocked" in r.get("reason", "")



def test_enable_covered_calls_on_allows_call_btc_prefer_roll_false():
    """When ENABLE_COVERED_CALLS=1 + prefer_roll=False, call BTC proceeds normally."""
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "NU261106C00015000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.50,
                "current_price": 0.20,
            }
        ],
        submit_success=True,
        has_shares=True,
    )

    mgr = CoveredCallManager(
        min_premium_usd=10.0,
        min_premium_pct=0.001,
    )

    # Set ENABLE_COVERED_CALLS=1
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        results = manage_or_roll_short_calls(
            broker,
            {"NU": 15.25},
            mgr,
            manage_dte_threshold=7,
            manage_itm_pct=0.02,
            profit_take_pct=0.60,
            prefer_roll=False,
            execute=True,
            auto_put_buyback=False,
        )
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify BTC order WAS submitted
    btc_orders = [o for o in broker.submitted_orders if o.get("side") == "buy"]
    assert len(btc_orders) >= 1
    assert btc_orders[0]["contract_symbol"] == "NU261106C00015000"

    # Verify call was processed
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) >= 1
    for r in call_results:
        assert "allow_call_closes=False_blocked" not in r.get("reason", "")


def test_enable_covered_calls_off_does_not_block_puts():
    """When ENABLE_COVERED_CALLS=0, put operations should still work normally."""
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

    # Set ENABLE_COVERED_CALLS=0
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "0"
        
        results = manage_or_roll_short_calls(
            broker,
            {"NU": 14.70},
            mgr,
            manage_dte_threshold=7,
            manage_itm_pct=0.02,
            profit_take_pct=0.60,
            prefer_roll=False,
            execute=True,
            auto_put_buyback=True,  # Allow put BTC
        )
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify put BTC order WAS submitted (not blocked by CC gate)
    assert len(broker.submitted_orders) >= 1
    order = broker.submitted_orders[0]
    assert order["contract_symbol"] == "NU261106P00015000"
    assert order["side"] == "buy"

    # Verify put was executed
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "btc_executed"


def test_enable_covered_calls_env_unset_blocks_call_closes(monkeypatch):
    """When ENABLE_COVERED_CALLS is unset/deleted, manage_or_roll_short_calls blocks call operations."""
    # Delete the env var (overriding the conftest autouse fixture)
    monkeypatch.delenv("ENABLE_COVERED_CALLS", raising=False)

    broker = MockBroker(
        option_positions=[
            {
                "symbol": "CPNG261121C00022000",
                "underlying": "CPNG",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.85,
                "current_price": 0.10,
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
        {"CPNG": 20.50},
        mgr,
        prefer_roll=False,
        execute=True,
        auto_put_buyback=False,
    )

    # Verify no call BTC orders submitted
    assert len(broker.submitted_orders) == 0, "ENABLE_COVERED_CALLS unset must block all call orders"

    # When ENABLE_COVERED_CALLS is unset and gate triggers, call operations are blocked
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) >= 1, "Expected at least one call result"
    for r in call_results:
        assert r["status"] == "skipped"
        assert "allow_call_closes=False_blocked" in r.get("reason", "")

