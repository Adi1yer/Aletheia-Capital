"""Test cost basis floor for covered call writes and rolls."""

import os
import pytest
from unittest.mock import MagicMock, patch
from src.options.covered_calls import (
    CoveredCallManager,
    _stock_cost_basis,
    STRIKE_BELOW_COST_BASIS,
    COST_BASIS_UNAVAILABLE,
)
from src.portfolio.models import Portfolio, Position


class TestStockCostBasis:
    """Test _stock_cost_basis helper function."""

    def test_returns_long_cost_basis_when_available(self):
        """Should return long_cost_basis from position."""
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        basis = _stock_cost_basis(portfolio, "AAPL")
        assert basis == 150.0

    def test_returns_none_when_ticker_not_in_positions(self):
        """Should return None when ticker has no position."""
        portfolio = Portfolio(cash=10000, positions={})
        basis = _stock_cost_basis(portfolio, "AAPL")
        assert basis is None

    def test_returns_none_when_cost_basis_is_zero(self):
        """Should return None when cost basis is 0."""
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=0.0),
            },
        )
        basis = _stock_cost_basis(portfolio, "AAPL")
        assert basis is None

    def test_returns_none_when_cost_basis_is_negative(self):
        """Should return None when cost basis is negative."""
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=-10.0),
            },
        )
        basis = _stock_cost_basis(portfolio, "AAPL")
        assert basis is None

    def test_returns_none_when_ticker_is_empty(self):
        """Should return None when ticker is empty string."""
        portfolio = Portfolio(cash=10000, positions={})
        basis = _stock_cost_basis(portfolio, "")
        assert basis is None


class TestCostBasisFloorOnWrites:
    """Test cost basis floor enforcement on new covered call writes."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with basic setup."""
        broker = MagicMock()
        broker.sync_portfolio.return_value = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        broker.get_option_positions.return_value = []
        broker.get_open_orders.return_value = []
        return broker

    def test_write_skipped_when_cost_basis_unavailable(self, mock_broker):
        """Should skip write and fail closed when cost basis is unavailable."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=0.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        manager = CoveredCallManager()
        results = manager.execute_covered_calls(
            broker=mock_broker,
            portfolio=portfolio,
            cc_lot_tickers=["AAPL"],
            cc_scores={"AAPL": 60},
            current_prices={"AAPL": 155.0},
        )

        assert len(results) == 1
        assert results[0]["underlying"] == "AAPL"
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == COST_BASIS_UNAVAILABLE

    def test_write_skipped_when_strike_below_cost_basis(self, mock_broker):
        """Should skip write when strike would be below cost basis."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        contract = {
            "symbol": "AAPL250117C00148000",
            "strike": 148.0,
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
            current_prices={"AAPL": 145.0},
        )

        assert len(results) == 1
        assert results[0]["underlying"] == "AAPL"
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == STRIKE_BELOW_COST_BASIS

    def test_write_succeeds_when_strike_above_cost_basis(self, mock_broker):
        """Should succeed when strike is above cost basis."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=150.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        contract = {
            "symbol": "AAPL250117C00155000",
            "strike": 155.0,
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
            current_prices={"AAPL": 152.0},
        )

        assert len(results) == 1
        assert results[0]["underlying"] == "AAPL"
        assert results[0]["status"] == "executed"
        assert results[0]["strike"] == 155.0

    def test_cost_basis_floor_combines_with_existing_strike_floor(self, mock_broker):
        """Should use max of cost basis floor and existing short strike floor."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=300, long_cost_basis=150.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        existing_short = {
            "symbol": "AAPL250117C00160000",
            "side": "short",
            "qty": 1,
            "option_type": "call",
            "underlying": "AAPL",
        }
        from src.options.wheel_lifecycle import parse_occ_symbol
        
        with patch("src.options.covered_calls.parse_occ_symbol") as mock_parse:
            mock_parse.return_value = {
                "underlying": "AAPL",
                "option_type": "call",
                "strike": 160.0,
                "expiry": "2025-01-17",
            }
            mock_broker.get_option_positions.return_value = [existing_short]

            contract = {
                "symbol": "AAPL250117C00162000",
                "strike": 162.0,
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

            assert len(results) == 1
            assert results[0]["status"] in ("executed", "partial")
            if results[0]["status"] in ("executed", "partial"):
                assert results[0]["strike"] >= 160.0


class TestCostBasisFloorFailClosed:
    """Test fail-closed behavior when cost basis is unavailable."""

    @pytest.fixture
    def mock_broker(self):
        """Mock broker with basic setup."""
        broker = MagicMock()
        broker.get_option_positions.return_value = []
        broker.get_open_orders.return_value = []
        return broker

    def test_fails_closed_with_missing_cost_basis(self, mock_broker):
        """Should fail closed (skip) when cost basis is missing."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        manager = CoveredCallManager()
        results = manager.execute_covered_calls(
            broker=mock_broker,
            portfolio=portfolio,
            cc_lot_tickers=["AAPL"],
            cc_scores={"AAPL": 60},
            current_prices={"AAPL": 155.0},
        )

        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == COST_BASIS_UNAVAILABLE

    def test_fails_closed_with_zero_cost_basis(self, mock_broker):
        """Should fail closed when cost basis is zero."""
        os.environ["ENABLE_COVERED_CALLS"] = "1"
        
        portfolio = Portfolio(
            cash=10000,
            positions={
                "AAPL": Position(long=200, long_cost_basis=0.0),
            },
        )
        mock_broker.sync_portfolio.return_value = portfolio

        manager = CoveredCallManager()
        results = manager.execute_covered_calls(
            broker=mock_broker,
            portfolio=portfolio,
            cc_lot_tickers=["AAPL"],
            cc_scores={"AAPL": 60},
            current_prices={"AAPL": 155.0},
        )

        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == COST_BASIS_UNAVAILABLE


class TestCostBasisFloorNeverTriggersUnwind:
    """Test that cost basis floor skips never trigger atomic unwind."""

    def test_cost_basis_unavailable_skip_does_not_unwind(self):
        """COST_BASIS_UNAVAILABLE skip must never trigger sale."""
        from src.options.covered_calls import tickers_needing_atomic_unwind

        cc_results = [
            {
                "underlying": "AAPL",
                "status": "skipped",
                "reason": COST_BASIS_UNAVAILABLE,
            }
        ]

        unwind = tickers_needing_atomic_unwind(
            cc_results,
            held_lot_tickers=["AAPL"],
            short_call_underlyings=set(),
        )

        assert "AAPL" not in unwind

    def test_strike_below_cost_basis_skip_does_not_unwind(self):
        """STRIKE_BELOW_COST_BASIS skip must never trigger sale."""
        from src.options.covered_calls import tickers_needing_atomic_unwind

        cc_results = [
            {
                "underlying": "AAPL",
                "status": "skipped",
                "reason": STRIKE_BELOW_COST_BASIS,
            }
        ]

        unwind = tickers_needing_atomic_unwind(
            cc_results,
            held_lot_tickers=["AAPL"],
            short_call_underlyings=set(),
        )

        assert "AAPL" not in unwind

    def test_cost_basis_floor_skips_not_in_attempted_tickers(self):
        """Cost basis floor skips should not be in cc_write_attempted_tickers."""
        from src.options.covered_calls import cc_write_attempted_tickers

        cc_results = [
            {
                "underlying": "AAPL",
                "status": "skipped",
                "reason": COST_BASIS_UNAVAILABLE,
            },
            {
                "underlying": "MSFT",
                "status": "skipped",
                "reason": STRIKE_BELOW_COST_BASIS,
            },
        ]

        attempted = cc_write_attempted_tickers(cc_results)

        assert "AAPL" not in attempted
        assert "MSFT" not in attempted
