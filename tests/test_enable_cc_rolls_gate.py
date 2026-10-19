"""Test ENABLE_CC_ROLLS gate for call rolls and defensive BTC."""

import os
import pytest
from unittest.mock import MagicMock
from src.options.wheel_lifecycle import manage_or_roll_short_calls
from src.options.covered_calls import CoveredCallManager
from src.portfolio.models import Portfolio, Position


class TestEnableCCRollsGateDefaultOff:
    """Test that ENABLE_CC_ROLLS defaults to off and blocks rolls."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with short call position."""
        broker = MagicMock()
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio

        short_call = {
            "symbol": "AAPL241220C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
            "avg_entry_price": 2.50,
            "mark_price": 0.50,
        }
        broker.get_option_positions.return_value = [short_call]
        return broker

    def test_rolls_blocked_when_enable_cc_rolls_unset(self, mock_broker):
        """Should block rolls when ENABLE_CC_ROLLS is unset."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        if "ENABLE_CC_ROLLS" in os.environ:
            del os.environ["ENABLE_CC_ROLLS"]

        cc_manager = CoveredCallManager()
        
        with MagicMock() as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            skipped = [r for r in results if r.get("status") == "skipped"]
            assert len(skipped) > 0
            assert any("allow_call_closes=False" in r.get("reason", "") for r in skipped)

    def test_rolls_blocked_when_enable_cc_rolls_zero(self, mock_broker):
        """Should block rolls when ENABLE_CC_ROLLS is '0'."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "0"

        cc_manager = CoveredCallManager()
        
        with MagicMock() as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            skipped = [r for r in results if r.get("status") == "skipped"]
            assert len(skipped) > 0

    def test_rolls_blocked_when_enable_cc_rolls_false(self, mock_broker):
        """Should block rolls when ENABLE_CC_ROLLS is 'false'."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "false"

        cc_manager = CoveredCallManager()
        
        with MagicMock() as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            skipped = [r for r in results if r.get("status") == "skipped"]
            assert len(skipped) > 0


class TestEnableCCRollsIndependentOfEnableCoveredCalls:
    """Test that ENABLE_CC_ROLLS is independent of ENABLE_COVERED_CALLS."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with short call position."""
        broker = MagicMock()
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio

        short_call = {
            "symbol": "AAPL241220C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
            "avg_entry_price": 2.50,
            "mark_price": 0.50,
        }
        broker.get_option_positions.return_value = [short_call]
        return broker

    def test_rolls_blocked_when_enable_covered_calls_on_but_rolls_off(self, mock_broker):
        """Should block rolls even when ENABLE_COVERED_CALLS=1 if ENABLE_CC_ROLLS=0."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "0"

        cc_manager = CoveredCallManager()
        
        with MagicMock() as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            btc_executed = [r for r in results if r.get("status") == "btc_executed"]
            assert len(btc_executed) == 0

    def test_rolls_blocked_when_enable_covered_calls_off_regardless_of_rolls(self, mock_broker):
        """Should block rolls when ENABLE_COVERED_CALLS=0 regardless of ENABLE_CC_ROLLS."""
        os.environ["ENABLE_COVERED_CALLS"] = "0"
        os.environ["ENABLE_CC_ROLLS"] = "1"

        cc_manager = CoveredCallManager()
        
        with MagicMock() as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            btc_executed = [r for r in results if r.get("status") == "btc_executed"]
            assert len(btc_executed) == 0


class TestEnableCCRollsAllowsRollsWhenOn:
    """Test that rolls proceed when both ENABLE_COVERED_CALLS=1 and ENABLE_CC_ROLLS=1."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with short call position ready to roll."""
        broker = MagicMock()
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=140.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio

        short_call = {
            "symbol": "AAPL241220C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
            "avg_entry_price": 2.50,
            "mark_price": 0.50,
        }
        broker.get_option_positions.return_value = [short_call]
        broker.get_open_orders.return_value = []

        btc_order = {
            "submitted": True,
            "fill_ok": True,
            "order_id": "btc-order-1",
            "filled_avg_price": 0.55,
        }
        
        sto_order = {
            "submitted": True,
            "fill_ok": True,
            "order_id": "sto-order-1",
            "filled_avg_price": 3.00,
        }
        
        broker.submit_option_order.side_effect = [btc_order, sto_order]
        
        new_contract = {
            "symbol": "AAPL250117C00160000",
            "strike": 160.0,
            "expiry": "2025-01-17",
            "mid_price": 3.00,
            "tradable": True,
        }
        broker.get_option_contracts.return_value = [new_contract]
        
        return broker

    def test_rolls_allowed_when_both_gates_on(self, mock_broker):
        """Should allow rolls when both ENABLE_COVERED_CALLS=1 and ENABLE_CC_ROLLS=1."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "1"

        cc_manager = CoveredCallManager()
        
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.wheel_lifecycle.parse_occ_symbol") as mock_parse:
            def parse_side_effect(symbol):
                if "C00155000" in symbol:
                    return {
                        "underlying": "AAPL",
                        "option_type": "call",
                        "strike": 155.0,
                        "expiry": "2024-12-20",
                        "symbol": symbol,
                    }
                elif "C00160000" in symbol:
                    return {
                        "underlying": "AAPL",
                        "option_type": "call",
                        "strike": 160.0,
                        "expiry": "2025-01-17",
                        "symbol": symbol,
                    }
                return None
            
            mock_parse.side_effect = parse_side_effect
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            btc_or_roll = [
                r for r in results 
                if r.get("status") in ("btc_executed", "roll_executed", "would_btc", "would_roll")
            ]
            assert len(btc_or_roll) > 0


class TestEnableCCRollsNoStandaloneBTC:
    """Test that no standalone BTC happens from roll path when rolls are off."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with short call position."""
        broker = MagicMock()
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio

        short_call = {
            "symbol": "AAPL241220C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
            "avg_entry_price": 2.50,
            "mark_price": 0.50,
        }
        broker.get_option_positions.return_value = [short_call]
        return broker

    def test_no_standalone_btc_when_rolls_off(self, mock_broker):
        """Should not execute standalone BTC from roll path when ENABLE_CC_ROLLS=0."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "0"

        cc_manager = CoveredCallManager()
        
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.wheel_lifecycle.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2024-12-20",
            }
            
            results = manage_or_roll_short_calls(
                broker=mock_broker,
                current_prices={"AAPL": 157.0},
                cc_manager=cc_manager,
                manage_dte_threshold=7,
                execute=True,
                prefer_roll=True,
            )

            btc_executed = [r for r in results if r.get("status") == "btc_executed"]
            assert len(btc_executed) == 0
            
            mock_broker.submit_option_order.assert_not_called()
