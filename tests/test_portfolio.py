"""Unit tests for portfolio management"""

import pytest
from src.portfolio.models import Portfolio, Position
from src.portfolio.manager import PortfolioManager
from src.agents.base import AgentSignal


class TestPortfolio:
    """Test Portfolio model"""
    
    def test_portfolio_initialization(self):
        """Test portfolio initializes correctly"""
        portfolio = Portfolio(cash=100000.0)
        assert portfolio.cash == 100000.0
        assert len(portfolio.positions) == 0
    
    def test_get_position_creates_if_missing(self):
        """Test get_position creates position if it doesn't exist"""
        portfolio = Portfolio(cash=100000.0)
        position = portfolio.get_position("AAPL")
        assert "AAPL" in portfolio.positions
        assert isinstance(position, Position)
    
    def test_get_position_returns_existing(self):
        """Test get_position returns existing position"""
        portfolio = Portfolio(cash=100000.0)
        portfolio.positions["AAPL"] = Position(long=100, long_cost_basis=150.0)
        position = portfolio.get_position("AAPL")
        assert position.long == 100
        assert position.long_cost_basis == 150.0
    
    def test_get_equity_calculation(self):
        """Test equity calculation"""
        portfolio = Portfolio(cash=100000.0)
        portfolio.positions["AAPL"] = Position(long=100, long_cost_basis=150.0)
        portfolio.positions["MSFT"] = Position(long=50, long_cost_basis=300.0)
        
        current_prices = {"AAPL": 160.0, "MSFT": 310.0}
        equity = portfolio.get_equity(current_prices)
        
        expected = 100000.0 + (100 * 160.0) + (50 * 310.0)
        assert equity == expected
    
    def test_get_equity_with_missing_prices(self):
        """Test equity calculation handles missing prices"""
        portfolio = Portfolio(cash=100000.0)
        portfolio.positions["AAPL"] = Position(long=100)
        
        current_prices = {}  # No prices
        equity = portfolio.get_equity(current_prices)
        assert equity == 100000.0  # Only cash


class TestPortfolioManager:
    """Test PortfolioManager"""
    
    @pytest.fixture
    def portfolio_manager(self):
        """Create portfolio manager instance"""
        return PortfolioManager()
    
    def test_aggregate_signals(self, portfolio_manager):
        """Test signal aggregation"""
        signals = {
            "AAPL": {
                "agent1": AgentSignal(signal="bullish", confidence=80, reasoning="Test"),
                "agent2": AgentSignal(signal="bullish", confidence=60, reasoning="Test"),
                "agent3": AgentSignal(signal="bearish", confidence=70, reasoning="Test"),
            }
        }
        weights = {"agent1": 1.0, "agent2": 1.0, "agent3": 1.0}
        
        aggregated = portfolio_manager._aggregate_signals("AAPL", signals, weights)
        
        assert isinstance(aggregated, dict)
        assert "signal" in aggregated or "weighted_score" in aggregated
    
    def test_generate_decisions(self, portfolio_manager, sample_portfolio):
        """Test decision generation"""
        tickers = ["AAPL", "MSFT"]
        agent_signals = {
            "agent1": {
                "AAPL": AgentSignal(signal="bullish", confidence=75, reasoning="Test"),
                "MSFT": AgentSignal(signal="neutral", confidence=50, reasoning="Test"),
            }
        }
        risk_analysis = {
            "AAPL": {"remaining_position_limit": 10000.0, "current_price": 150.0},
            "MSFT": {"remaining_position_limit": 5000.0, "current_price": 300.0},
        }
        agent_weights = {"agent1": 1.0}
        
        decisions = portfolio_manager.generate_decisions(
            tickers=tickers,
            agent_signals=agent_signals,
            risk_analysis=risk_analysis,
            portfolio=sample_portfolio,
            agent_weights=agent_weights,
        )
        
        assert isinstance(decisions, dict)
        # Decisions should respect risk limits

