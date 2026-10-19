"""Test that pending/open orders count toward contract cap."""

import os
import pytest
from unittest.mock import MagicMock
from src.options.covered_calls import (
    CoveredCallManager,
    live_coverage_sto_qty,
    _working_short_calls,
)
from src.portfolio.models import Portfolio, Position


class TestWorkingShortCalls:
    """Test _working_short_calls helper counts unfilled STO call orders."""

    def test_counts_pending_sell_to_open_calls(self):
        """Should count pending sell-to-open call orders."""
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        open_orders = [
            {
                "symbol": "AAPL250117C00155000",
                "side": "sell",
                "status": "pending",
                "qty": 2,
            }
        ]
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            working = _working_short_calls(open_orders)
            
            assert working["AAPL"] == 2

    def test_excludes_filled_orders(self):
        """Should exclude filled orders."""
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        open_orders = [
            {
                "symbol": "AAPL250117C00155000",
                "side": "sell",
                "status": "filled",
                "qty": 1,
            }
        ]
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            working = _working_short_calls(open_orders)
            
            assert "AAPL" not in working

    def test_excludes_canceled_orders(self):
        """Should exclude canceled orders."""
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        open_orders = [
            {
                "symbol": "AAPL250117C00155000",
                "side": "sell",
                "status": "canceled",
                "qty": 1,
            }
        ]
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            working = _working_short_calls(open_orders)
            
            assert "AAPL" not in working

    def test_counts_multiple_pending_orders_same_underlying(self):
        """Should sum multiple pending orders for same underlying."""
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        open_orders = [
            {
                "symbol": "AAPL250117C00155000",
                "side": "sell",
                "status": "pending",
                "qty": 1,
            },
            {
                "symbol": "AAPL250117C00160000",
                "side": "sell",
                "status": "new",
                "qty": 1,
            }
        ]
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            working = _working_short_calls(open_orders)
            
            assert working["AAPL"] == 2


class TestLiveCoverageSTOQtyCountsPendingOrders:
    """Test that live_coverage_sto_qty counts pending orders toward cap."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with positions and pending orders."""
        broker = MagicMock()
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=300, long_cost_basis=150.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio
        
        short_call = {
            "symbol": "AAPL250117C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
        }
        broker.get_option_positions.return_value = [short_call]
        
        pending_order = {
            "symbol": "AAPL250117C00160000",
            "side": "sell",
            "status": "pending",
            "qty": 1,
        }
        broker.get_open_orders.return_value = [pending_order]
        
        return broker

    def test_pending_orders_reduce_available_slots(self, mock_broker):
        """Should reduce available STO qty by pending orders."""
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 160.0,
                "expiry": "2025-01-17",
            }
            
            sto_qty = live_coverage_sto_qty(mock_broker, "AAPL", 10)
            
            assert sto_qty == 1

    def test_no_slots_when_pending_fills_capacity(self, mock_broker):
        """Should return 0 when pending orders fill all capacity."""
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio
        
        short_call = {
            "symbol": "AAPL250117C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
        }
        mock_broker.get_option_positions.return_value = [short_call]
        
        pending_order = {
            "symbol": "AAPL250117C00160000",
            "side": "sell",
            "status": "pending",
            "qty": 1,
        }
        mock_broker.get_open_orders.return_value = [pending_order]
        
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 160.0,
                "expiry": "2025-01-17",
            }
            
            sto_qty = live_coverage_sto_qty(mock_broker, "AAPL", 10)
            
            assert sto_qty == 0


class TestPendingOrdersPreventNakedWrites:
    """Test that pending orders prevent naked call writes."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with 200 shares and 1 pending call order."""
        broker = MagicMock()
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        broker.sync_portfolio.return_value = portfolio
        
        broker.get_option_positions.return_value = []
        
        pending_order = {
            "symbol": "AAPL250117C00155000",
            "side": "sell",
            "status": "pending",
            "qty": 1,
        }
        broker.get_open_orders.return_value = [pending_order]
        
        return broker

    def test_cannot_write_second_call_with_pending_order(self, mock_broker):
        """Should prevent second write when pending order + shares = capacity."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "1"
        
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            portfolio = Portfolio(
                cash=10000,
                positions={
                    "AAPL": Position(long=200, long_cost_basis=150.0),
                },
            )
            
            contract = {
                "symbol": "AAPL250117C00160000",
                "strike": 160.0,
                "expiry": "2025-01-17",
                "mid_price": 2.50,
                "tradable": True,
            }
            mock_broker.get_option_contracts.return_value = [contract]

            manager = CoveredCallManager()
            results = manager.execute_covered_calls(
                broker=mock_broker,
                portfolio=portfolio,
                cc_lot_tickers=["AAPL"],
                cc_scores={"AAPL": 60},
                current_prices={"AAPL": 155.0},
            )

            executed = [r for r in results if r.get("status") == "executed"]
            assert len(executed) == 0

    def test_can_write_when_pending_fills_and_capacity_increases(self, mock_broker):
        """Should allow write after pending fills and capacity increases."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        os.environ["ENABLE_CC_ROLLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=300, long_cost_basis=150.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio
        
        filled_call = {
            "symbol": "AAPL250117C00155000",
            "side": "short",
            "qty": 1,
            "underlying": "AAPL",
            "option_type": "call",
        }
        mock_broker.get_option_positions.return_value = [filled_call]
        
        mock_broker.get_open_orders.return_value = []
        
        from src.options.wheel_lifecycle import parse_occ_symbol
        from unittest.mock import patch
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 155.0,
                "expiry": "2025-01-17",
            }
            
            contract = {
                "symbol": "AAPL250117C00160000",
                "strike": 160.0,
                "expiry": "2025-01-17",
                "mid_price": 2.50,
                "tradable": True,
            }
            mock_broker.get_option_contracts.return_value = [contract]
            
            order = {
                "submitted": True,
                "fill_ok": True,
                "order_id": "test-order-1",
            }
            mock_broker.submit_option_order.return_value = order

            manager = CoveredCallManager()
            results = manager.execute_covered_calls(
                broker=mock_broker,
                portfolio=portfolio,
                cc_lot_tickers=["AAPL"],
                cc_scores={"AAPL": 60},
                current_prices={"AAPL": 155.0},
            )

            executed = [r for r in results if r.get("status") in ("executed", "partial")]
            assert len(executed) > 0
