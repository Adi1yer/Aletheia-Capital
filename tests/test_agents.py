"""Unit tests for investment agents"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.agents.warren_buffett import WarrenBuffettAgent
from src.agents.base import AgentSignal
from src.data.models import Price, FinancialMetrics, LineItem


class TestWarrenBuffettAgent:
    """Test Warren Buffett agent"""
    
    def test_agent_initialization(self):
        """Test agent initializes correctly"""
        agent = WarrenBuffettAgent(weight=1.0)
        assert agent.name == "Warren Buffett"
        assert agent.weight == 1.0
        assert agent.investing_style is not None
        assert agent.data_provider is not None
    
    @patch('src.agents.warren_buffett.get_llm_for_agent')
    @patch('src.agents.warren_buffett.get_data_provider')
    def test_analyze_with_data(self, mock_get_provider, mock_get_llm, sample_prices, sample_metrics, sample_line_items):
        """Test agent analysis with valid data"""
        # Setup mocks
        mock_provider = Mock()
        mock_provider.get_prices = Mock(return_value=sample_prices)
        mock_provider.get_financial_metrics = Mock(return_value=sample_metrics)
        mock_provider.get_line_items = Mock(return_value=sample_line_items)
        mock_provider.get_market_cap = Mock(return_value=2500000000000.0)
        mock_get_provider.return_value = mock_provider
        
        mock_llm = Mock()
        mock_llm_with_structure = Mock()
        mock_llm_with_structure.invoke = Mock(return_value=AgentSignal(
            signal="buy",
            confidence=80,
            reasoning="Strong moat and consistent earnings"
        ))
        mock_llm.with_structured_output = Mock(return_value=mock_llm_with_structure)
        mock_get_llm.return_value = mock_llm
        
        # Test
        agent = WarrenBuffettAgent()
        result = agent.analyze("AAPL", "2024-01-01", "2024-01-02")
        
        # Assertions
        assert isinstance(result, AgentSignal)
        assert result.signal in ["buy", "sell", "hold", "neutral"]
        assert 0 <= result.confidence <= 100
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0
    
    @patch('src.agents.warren_buffett.get_data_provider')
    def test_analyze_without_data(self, mock_get_provider):
        """Test agent handles missing data gracefully"""
        mock_provider = Mock()
        mock_provider.get_prices = Mock(return_value=[])
        mock_provider.get_financial_metrics = Mock(return_value=[])
        mock_provider.get_line_items = Mock(return_value=[])
        mock_get_provider.return_value = mock_provider
        
        agent = WarrenBuffettAgent()
        result = agent.analyze("INVALID", "2024-01-01", "2024-01-02")
        
        assert isinstance(result, AgentSignal)
        assert result.signal in ["buy", "sell", "hold", "neutral"]
        assert result.confidence >= 0
    
    def test_analyze_multiple_tickers(self, sample_prices, sample_metrics, sample_line_items):
        """Test analyzing multiple tickers"""
        with patch('src.agents.warren_buffett.get_data_provider') as mock_get_provider, \
             patch('src.agents.warren_buffett.get_llm_for_agent') as mock_get_llm:
            
            mock_provider = Mock()
            mock_provider.get_prices = Mock(return_value=sample_prices)
            mock_provider.get_financial_metrics = Mock(return_value=sample_metrics)
            mock_provider.get_line_items = Mock(return_value=sample_line_items)
            mock_provider.get_market_cap = Mock(return_value=2500000000000.0)
            mock_get_provider.return_value = mock_provider
            
            mock_llm = Mock()
            mock_llm_with_structure = Mock()
            mock_llm_with_structure.invoke = Mock(return_value=AgentSignal(
                signal="buy",
                confidence=75,
                reasoning="Test"
            ))
            mock_llm.with_structured_output = Mock(return_value=mock_llm_with_structure)
            mock_get_llm.return_value = mock_llm
            
            agent = WarrenBuffettAgent()
            results = agent.analyze_multiple(["AAPL", "MSFT"], "2024-01-01", "2024-01-02")
            
            assert isinstance(results, dict)
            assert "AAPL" in results
            assert "MSFT" in results
            assert all(isinstance(signal, AgentSignal) for signal in results.values())


class TestAgentSignal:
    """Test AgentSignal model"""
    
    def test_agent_signal_creation(self):
        """Test creating an agent signal"""
        signal = AgentSignal(
            signal="buy",
            confidence=75,
            reasoning="Test reasoning"
        )
        assert signal.signal == "buy"
        assert signal.confidence == 75
        assert signal.reasoning == "Test reasoning"
    
    def test_agent_signal_validation(self):
        """Test signal validation"""
        # Valid signals
        valid_signals = ["buy", "sell", "hold", "neutral"]
        for sig in valid_signals:
            signal = AgentSignal(
                signal=sig,
                confidence=50,
                reasoning="Test"
            )
            assert signal.signal == sig
        
        # Confidence bounds
        signal = AgentSignal(signal="buy", confidence=0, reasoning="Test")
        assert signal.confidence == 0
        
        signal = AgentSignal(signal="buy", confidence=100, reasoning="Test")
        assert signal.confidence == 100

