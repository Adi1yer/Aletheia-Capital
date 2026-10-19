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
    import os
    
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

    # Set ENABLE_COVERED_CALLS=1 so calls aren't blocked
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
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
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify no BTC order was submitted
    assert len(broker.submitted_orders) == 0

    # Verify put was skipped with correct status
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) == 1
    assert put_results[0]["status"] == "skipped"
    # Reason can vary depending on path (AUTO_PUT_BUYBACK=0 or allow_put_closes=False)
    assert ("AUTO_PUT_BUYBACK=0" in put_results[0]["reason"] or 
            "allow_put_closes=False_blocked" in put_results[0]["reason"])
    assert "put_near_itm" in put_results[0]["reason"]


def test_put_btc_blocked_with_cc_on_but_auto_put_buyback_false():
    """Put BTC remains blocked when ENABLE_COVERED_CALLS=1 but auto_put_buyback=False.
    
    This test proves that the covered-calls flip keeps put BTC off.
    """
    import os
    
    broker = MockBroker(
        option_positions=[
            {
                "symbol": "TEST261106P00020000",
                "side": "short",
                "qty": 1,
                "avg_entry_price": 0.80,
                "current_price": 1.20,
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

    # Set CC on, auto_put_buyback off — the production config after the flip
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        results = manage_or_roll_short_calls(
            broker,
            {"TEST": 19.50},  # Underlying below strike $20 → put is ITM
            mgr,
            manage_itm_pct=0.02,
            prefer_roll=True,
            execute=True,
            auto_put_buyback=False,  # Explicitly off
        )
        
        # Should skip the put (no BTC), regardless of ENABLE_COVERED_CALLS=1
        put_results = [r for r in results if r.get("option_type") == "put"]
        assert len(put_results) == 1
        assert put_results[0]["status"] == "skipped"
        assert put_results[0]["contract_symbol"] == "TEST261106P00020000"
        assert len(broker.submitted_orders) == 0  # No BTC order submitted
    finally:
        if old_val is not None:
            os.environ["ENABLE_COVERED_CALLS"] = old_val
        else:
            os.environ.pop("ENABLE_COVERED_CALLS", None)


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
    import os
    
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

    # Set ENABLE_COVERED_CALLS=1 so calls work
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
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
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify BTC order was submitted for call
    btc_orders = [o for o in broker.submitted_orders if o["side"] == "buy"]
    assert len(btc_orders) >= 1

    # Verify call was processed (not skipped)
    call_results = [r for r in results if r.get("option_type") == "call"]
    assert len(call_results) > 0
    assert not any(r.get("status") == "skipped" for r in call_results)


def test_manage_or_roll_multiple_puts_all_skipped_when_flag_off():
    """When AUTO_PUT_BUYBACK=0, all put BTC should be skipped."""
    import os
    
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

    # Set ENABLE_COVERED_CALLS=1 so calls aren't blocked
    old_val = os.environ.get("ENABLE_COVERED_CALLS")
    try:
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
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
    finally:
        if old_val is None:
            os.environ.pop("ENABLE_COVERED_CALLS", None)
        else:
            os.environ["ENABLE_COVERED_CALLS"] = old_val

    # Verify no BTC orders submitted
    assert len(broker.submitted_orders) == 0

    # Verify all puts were skipped
    put_results = [r for r in results if r.get("option_type") == "put"]
    assert len(put_results) >= 2
    for r in put_results:
        assert r["status"] == "skipped"
        # Reason can vary depending on path
        assert ("AUTO_PUT_BUYBACK=0" in r["reason"] or 
                "allow_put_closes=False_blocked" in r["reason"])


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


def test_defensive_check_logs_error_when_put_btc_executed_with_flag_off(caplog):
    """If manage_short_options returns btc_executed for a put with auto_put_buyback=False, log ERROR and keep status."""
    from unittest.mock import patch
    import logging
    
    # Configure structlog to emit to standard logging so caplog can capture
    import structlog
    
    # Save original config
    original_config = structlog.get_config()
    
    try:
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        
        broker = MockBroker(
            option_positions=[],
            submit_success=True,
        )

        mgr = CoveredCallManager(
            min_premium_usd=10.0,
            min_premium_pct=0.001,
        )

        # Set ENABLE_COVERED_CALLS=1 so calls aren't blocked
        import os
        old_val = os.environ.get("ENABLE_COVERED_CALLS")
        try:
            os.environ["ENABLE_COVERED_CALLS"] = "1"
            
            # Mock manage_short_options to return btc_executed for a put (simulating control breach)
            fake_results = [
                {
                    "contract_symbol": "NU261106P00015000",
                    "underlying": "NU",
                    "status": "btc_executed",
                    "reason": "put_near_itm",
                    "dte": 6,
                    "qty": 1,
                    "option_type": "put",
                    "order": {"id": "test-order-123"},
                }
            ]
            
            with patch("src.options.wheel_lifecycle.manage_short_options", return_value=fake_results):
                with caplog.at_level(logging.ERROR, logger="src.options.wheel_lifecycle"):
                    results = manage_or_roll_short_calls(
                        broker,
                        {"NU": 14.70},
                        mgr,
                        prefer_roll=False,
                        execute=True,
                        auto_put_buyback=False,
                    )
        finally:
            if old_val is None:
                os.environ.pop("ENABLE_COVERED_CALLS", None)
            else:
                os.environ["ENABLE_COVERED_CALLS"] = old_val
        
        # Verify ERROR log with symbol and order_id
        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_records) > 0, "Expected ERROR log record"
        
        # Check log contains symbol and order_id
        error_msg = " ".join(str(r.getMessage()) for r in error_records)
        assert "NU261106P00015000" in error_msg, "ERROR log must include symbol"
        assert "test-order-123" in error_msg, "ERROR log must include order_id"
        
        # Verify status is KEPT as btc_executed (not relabeled)
        put_results = [r for r in results if r.get("option_type") == "put"]
        assert len(put_results) == 1
        assert put_results[0]["status"] == "btc_executed", "Status must be kept as btc_executed to not hide the fill"
        assert put_results[0]["contract_symbol"] == "NU261106P00015000"
    finally:
        # Reset structlog to original config
        structlog.configure(**original_config)
