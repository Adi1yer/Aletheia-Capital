"""Unit tests for risk management"""

import pytest
from src.risk.manager import RiskManager
from src.portfolio.models import Portfolio, Position


class TestRiskManager:
    """Test RiskManager"""

    @pytest.fixture
    def risk_manager(self):
        """Create risk manager instance"""
        return RiskManager()

    def test_calculate_volatility_adjusted_limit_low_vol(self, risk_manager):
        """Test volatility adjustment for low volatility stocks"""
        limit = risk_manager._calculate_volatility_adjusted_limit(0.10)  # 10% volatility
        assert limit > 0.20  # Should be higher than base for low vol

    def test_calculate_volatility_adjusted_limit_high_vol(self, risk_manager):
        """Test volatility adjustment for high volatility stocks"""
        limit = risk_manager._calculate_volatility_adjusted_limit(0.60)  # 60% volatility
        assert limit < 0.20  # Should be lower than base for high vol

    def test_calculate_correlation_multiplier(self, risk_manager):
        """Test correlation multiplier calculation"""
        # High correlation should reduce limit
        high_corr = risk_manager._calculate_correlation_multiplier(0.85)
        assert high_corr < 1.0

        # Low correlation should increase limit
        low_corr = risk_manager._calculate_correlation_multiplier(0.15)
        assert low_corr > 1.0

        # Moderate correlation should be neutral
        moderate_corr = risk_manager._calculate_correlation_multiplier(0.50)
        assert 0.95 <= moderate_corr <= 1.05

    @pytest.mark.skip(reason="Requires data provider mocking")
    def test_calculate_position_limits(self, risk_manager, sample_portfolio):
        """Test position limit calculation"""
        # This would require mocking the data provider
        # For now, we'll test the helper methods
        pass
