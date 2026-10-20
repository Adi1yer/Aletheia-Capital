"""Tests for fail-closed pending orders cap enforcement in live_coverage_sto_qty."""

import pytest
from unittest.mock import MagicMock
from src.options.covered_calls import live_coverage_sto_qty


class TestFailClosedPendingOrdersFetch:
    """Test that live_coverage_sto_qty is fail-closed when fetching pending orders."""

    def test_broker_without_get_open_orders_returns_zero(self):
        """If broker lacks get_open_orders method, fail closed and return 0."""
        broker = MagicMock()
        # Portfolio: 300 shares (3 lots)
        portfolio = MagicMock()
        portfolio.long_qty.return_value = 300
        broker.sync_portfolio.return_value = portfolio
        
        # Option positions: 1 short call (2 slots remain)
        option_positions = [
            {
                "symbol": "AAPL240119C00150000",
                "side": "short",
                "underlying": "AAPL",
                "option_type": "call",
                "qty": 1,
            }
        ]
        broker.get_option_positions.return_value = option_positions
        
        # Broker does NOT have get_open_orders attribute
        if hasattr(broker, "get_open_orders"):
            delattr(broker, "get_open_orders")
        
        # Should return 0 (fail closed) not 2 (which would be slots - filled)
        result = live_coverage_sto_qty(broker, "AAPL", requested=2)
        
        assert result == 0

    def test_get_open_orders_raises_returns_zero(self):
        """If get_open_orders raises, fail closed and return 0."""
        broker = MagicMock()
        # Portfolio: 300 shares
        portfolio = MagicMock()
        portfolio.long_qty.return_value = 300
        broker.sync_portfolio.return_value = portfolio
        
        # Option positions: 1 short call
        option_positions = [
            {
                "symbol": "AAPL240119C00150000",
                "side": "short",
                "underlying": "AAPL",
                "option_type": "call",
                "qty": 1,
            }
        ]
        broker.get_option_positions.return_value = option_positions
        
        # get_open_orders raises
        broker.get_open_orders.side_effect = Exception("API failure")
        
        # Should return 0 (fail closed)
        result = live_coverage_sto_qty(broker, "AAPL", requested=2)
        
        assert result == 0

    def test_get_open_orders_succeeds_normal_path(self):
        """When get_open_orders succeeds, calculate normally."""
        broker = MagicMock()
        # Portfolio: 300 shares (3 lots)
        portfolio = MagicMock()
        portfolio.long_qty.return_value = 300
        broker.sync_portfolio.return_value = portfolio
        
        # Option positions: 1 filled short call
        option_positions = [
            {
                "symbol": "AAPL240119C00150000",
                "side": "short",
                "underlying": "AAPL",
                "option_type": "call",
                "qty": 1,
            }
        ]
        broker.get_option_positions.return_value = option_positions
        
        # Open orders: 1 pending short call
        open_orders = [
            {
                "symbol": "AAPL240119C00155000",
                "side": "sell",
                "status": "pending_new",
                "qty": 1,
            }
        ]
        broker.get_open_orders.return_value = open_orders
        
        # 3 slots - 1 filled - 1 pending = 1 available
        result = live_coverage_sto_qty(broker, "AAPL", requested=2)
        
        assert result == 1

    def test_get_open_orders_empty_list_normal_path(self):
        """When get_open_orders returns empty list, calculate normally."""
        broker = MagicMock()
        # Portfolio: 200 shares (2 lots)
        portfolio = MagicMock()
        portfolio.long_qty.return_value = 200
        broker.sync_portfolio.return_value = portfolio
        
        # Option positions: 0 short calls
        broker.get_option_positions.return_value = []
        
        # Open orders: empty (no pending)
        broker.get_open_orders.return_value = []
        
        # 2 slots - 0 filled - 0 pending = 2 available
        result = live_coverage_sto_qty(broker, "AAPL", requested=2)
        
        assert result == 2

    def test_fail_closed_prevents_overhedge(self):
        """Fail-closed prevents naked short when we can't verify pending orders."""
        broker = MagicMock()
        # Portfolio: 100 shares (1 lot)
        portfolio = MagicMock()
        portfolio.long_qty.return_value = 100
        broker.sync_portfolio.return_value = portfolio
        
        # Option positions: 0 filled short calls
        broker.get_option_positions.return_value = []
        
        # get_open_orders fails (might have pending orders we can't see)
        broker.get_open_orders.side_effect = Exception("Network timeout")
        
        # Without fail-closed: would return 1 (allowing naked short if order pending)
        # With fail-closed: returns 0
        result = live_coverage_sto_qty(broker, "AAPL", requested=1)
        
        assert result == 0
