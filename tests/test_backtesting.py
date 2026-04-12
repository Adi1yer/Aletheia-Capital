"""Tests for backtesting engine"""

import pytest
from unittest.mock import Mock, patch
from src.backtesting.engine import BacktestingEngine, BacktestResult
from src.portfolio.models import Portfolio


class TestBacktestingEngine:
    """Test BacktestingEngine"""
    
    @pytest.fixture
    def backtesting_engine(self):
        """Create backtesting engine instance"""
        with patch('src.backtesting.engine.initialize_agents'), \
             patch('src.backtesting.engine.get_data_provider'):
            return BacktestingEngine()
    
    def test_backtest_result_model(self):
        """Test BacktestResult model"""
        result = BacktestResult(
            start_date="2024-01-01",
            end_date="2024-01-31",
            initial_capital=100000.0,
            final_capital=105000.0,
            total_return_pct=5.0,
            sharpe_ratio=1.2,
            max_drawdown=-2.5,
            equity_curve=[],
        )
        
        assert result.start_date == "2024-01-01"
        assert result.end_date == "2024-01-31"
        assert result.total_return_pct == 5.0
        assert result.sharpe_ratio == 1.2
    
    @pytest.mark.skip(reason="Requires full system integration")
    def test_run_backtest(self, backtesting_engine):
        """Test running a backtest"""
        # This would require mocking all dependencies
        # and providing historical data
        pass
    
    def test_portfolio_equity_calculation(self):
        """Test portfolio equity calculation in backtest context"""
        portfolio = Portfolio(cash=100000.0)
        portfolio.positions["AAPL"] = Mock()
        portfolio.positions["AAPL"].long = 100
        portfolio.positions["AAPL"].short = 0
        
        current_prices = {"AAPL": 150.0}
        equity = portfolio.get_equity(current_prices)
        
        assert equity == 100000.0 + (100 * 150.0)

