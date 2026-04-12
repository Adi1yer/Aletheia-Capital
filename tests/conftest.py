"""Pytest configuration and fixtures"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timedelta
from src.agents.base import BaseAgent, AgentSignal
from src.portfolio.models import Portfolio, Position
from src.data.models import Price, FinancialMetrics, LineItem


@pytest.fixture
def sample_ticker():
    """Sample ticker for testing"""
    return "AAPL"


@pytest.fixture
def sample_dates():
    """Sample date range for testing"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    return start_date, end_date


@pytest.fixture
def sample_prices():
    """Sample price data"""
    return [
        Price(
            time="2024-01-01T00:00:00Z",
            open=150.0,
            high=155.0,
            low=149.0,
            close=153.0,
            volume=1000000,
        ),
        Price(
            time="2024-01-02T00:00:00Z",
            open=153.0,
            high=156.0,
            low=152.0,
            close=155.0,
            volume=1200000,
        ),
    ]


@pytest.fixture
def sample_metrics():
    """Sample financial metrics"""
    return [
        FinancialMetrics(
            period="2024-01-01",
            pe_ratio=25.0,
            pb_ratio=5.0,
            debt_to_equity=0.5,
            roe=0.15,
            roa=0.10,
            current_ratio=2.0,
            quick_ratio=1.5,
        )
    ]


@pytest.fixture
def sample_line_items():
    """Sample line items"""
    return [
        LineItem(
            period="2024-01-01",
            revenue=1000000000.0,
            net_income=200000000.0,
            free_cash_flow=150000000.0,
            ebitda=300000000.0,
            total_debt=500000000.0,
            cash_and_equivalents=1000000000.0,
            shareholders_equity=2000000000.0,
            total_assets=3000000000.0,
            operating_income=250000000.0,
            gross_profit=400000000.0,
        )
    ]


@pytest.fixture
def mock_data_provider(sample_prices, sample_metrics, sample_line_items):
    """Mock data provider"""
    provider = Mock()
    provider.get_prices = Mock(return_value=sample_prices)
    provider.get_financial_metrics = Mock(return_value=sample_metrics)
    provider.get_line_items = Mock(return_value=sample_line_items)
    provider.get_market_cap = Mock(return_value=2500000000000.0)
    provider.get_news = Mock(return_value=[])
    provider.get_insider_trades = Mock(return_value=[])
    return provider


@pytest.fixture
def sample_portfolio():
    """Sample portfolio for testing"""
    portfolio = Portfolio(cash=100000.0)
    portfolio.positions["AAPL"] = Position(long=100, long_cost_basis=150.0)
    portfolio.positions["MSFT"] = Position(long=50, long_cost_basis=300.0)
    return portfolio


@pytest.fixture
def sample_agent_signal():
    """Sample agent signal"""
    return AgentSignal(
        signal="buy",
        confidence=75,
        reasoning="Strong fundamentals and growth potential",
    )


@pytest.fixture
def mock_llm():
    """Mock LLM for testing"""
    llm = Mock()
    llm.with_structured_output = Mock(return_value=llm)
    llm.invoke = Mock(return_value=AgentSignal(
        signal="buy",
        confidence=75,
        reasoning="Test reasoning"
    ))
    return llm

