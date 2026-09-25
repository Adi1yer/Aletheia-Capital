"""Tests for crisis overlay module."""

import pytest
from datetime import date

from src.backtesting.wheel_hybrid.crisis_overlay import (
    CrisisOverlay,
    CrisisOverlayConfig,
    CrisisRegime,
    calculate_sma,
)


class TestCalculateSMA:
    """Tests for SMA calculation."""
    
    def test_sma_simple(self):
        prices = [100, 102, 104, 106, 108]
        sma = calculate_sma(prices, 5)
        assert sma == pytest.approx(104.0)
    
    def test_sma_insufficient_data(self):
        prices = [100, 102, 104]
        sma = calculate_sma(prices, 5)
        assert sma is None
    
    def test_sma_window_equal_length(self):
        prices = [100, 105, 110]
        sma = calculate_sma(prices, 3)
        assert sma == pytest.approx(105.0)
    
    def test_sma_trailing_window(self):
        prices = [100, 100, 100, 100, 200, 200, 200, 200, 200, 200]
        sma = calculate_sma(prices, 5)
        # Last 5: [200, 200, 200, 200, 200]
        assert sma == pytest.approx(200.0)


class TestCrisisOverlay:
    """Tests for CrisisOverlay class."""
    
    def test_overlay_disabled(self):
        config = CrisisOverlayConfig(enabled=False)
        overlay = CrisisOverlay(config)
        
        # Should never trigger rebalance when disabled
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 15), 100.0, 105.0
        )
        
        assert not should_rebalance
        assert regime == CrisisRegime.RISK_ON
    
    def test_simple_regime_risk_on(self):
        config = CrisisOverlayConfig(
            enabled=True,
            sma_window=200,
            rebalance_mode="monthly",
            hysteresis_pct=0.0,
        )
        overlay = CrisisOverlay(config)
        
        # SPY > SMA = risk-on
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 31), 110.0, 100.0
        )
        
        assert should_rebalance  # First call always rebalances
        assert regime == CrisisRegime.RISK_ON
    
    def test_simple_regime_risk_off(self):
        config = CrisisOverlayConfig(
            enabled=True,
            sma_window=200,
            rebalance_mode="monthly",
            hysteresis_pct=0.0,
        )
        overlay = CrisisOverlay(config)
        
        # SPY <= SMA = risk-off
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 31), 95.0, 100.0
        )
        
        assert should_rebalance
        assert regime == CrisisRegime.RISK_OFF
    
    def test_monthly_rebalance(self):
        config = CrisisOverlayConfig(
            enabled=True,
            rebalance_mode="monthly",
        )
        overlay = CrisisOverlay(config)
        
        # First call: rebalance
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 31), 110.0, 100.0
        )
        assert should_rebalance
        overlay.update_regime(date(2020, 1, 31), regime)
        
        # Same month: no rebalance
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 31), 110.0, 100.0
        )
        assert not should_rebalance
        
        # Next month: rebalance
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 2, 28), 110.0, 100.0
        )
        assert should_rebalance
    
    def test_signal_change_rebalance(self):
        config = CrisisOverlayConfig(
            enabled=True,
            rebalance_mode="signal_change",
            hysteresis_pct=0.0,
        )
        overlay = CrisisOverlay(config)
        
        # Start risk-on
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 15), 110.0, 100.0
        )
        assert should_rebalance
        assert regime == CrisisRegime.RISK_ON
        overlay.update_regime(date(2020, 1, 15), regime)
        
        # Still risk-on: no rebalance
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 16), 111.0, 100.0
        )
        assert not should_rebalance
        
        # Switch to risk-off: rebalance
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 17), 95.0, 100.0
        )
        assert should_rebalance
        assert regime == CrisisRegime.RISK_OFF
    
    def test_hysteresis_prevents_whipsaw(self):
        config = CrisisOverlayConfig(
            enabled=True,
            rebalance_mode="signal_change",
            hysteresis_pct=0.02,  # 2% buffer
        )
        overlay = CrisisOverlay(config)
        
        # Start risk-on (SPY 102, SMA 100)
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 15), 102.0, 100.0
        )
        assert regime == CrisisRegime.RISK_ON
        overlay.update_regime(date(2020, 1, 15), regime)
        
        # SPY drops to 99.5 (above lower threshold 98): stay risk-on
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 16), 99.5, 100.0
        )
        assert not should_rebalance
        assert regime == CrisisRegime.RISK_ON
        
        # SPY drops to 97.5 (below lower threshold 98): switch to risk-off
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 17), 97.5, 100.0
        )
        assert should_rebalance
        assert regime == CrisisRegime.RISK_OFF
        overlay.update_regime(date(2020, 1, 17), regime)
        
        # SPY rises to 100.5 (below upper threshold 102): stay risk-off
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 18), 100.5, 100.0
        )
        assert not should_rebalance
        assert regime == CrisisRegime.RISK_OFF
        
        # SPY rises to 103 (above upper threshold 102): switch to risk-on
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 19), 103.0, 100.0
        )
        assert should_rebalance
        assert regime == CrisisRegime.RISK_ON
    
    def test_get_target_allocation(self):
        config = CrisisOverlayConfig(
            enabled=True,
            risk_on_asset="SPY",
            risk_off_asset="BIL",
        )
        overlay = CrisisOverlay(config)
        
        # Default is risk-on
        assert overlay.get_target_allocation() == "SPY"
        
        # Switch to risk-off
        overlay.current_regime = CrisisRegime.RISK_OFF
        assert overlay.get_target_allocation() == "BIL"
    
    def test_stats_tracking(self):
        config = CrisisOverlayConfig(
            enabled=True,
            rebalance_mode="signal_change",
        )
        overlay = CrisisOverlay(config)
        
        # Start risk-on
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 1, 15), 110.0, 100.0
        )
        overlay.update_regime(date(2020, 1, 15), regime)
        
        # Switch to risk-off
        should_rebalance, regime = overlay.should_rebalance(
            date(2020, 2, 15), 95.0, 100.0
        )
        overlay.update_regime(date(2020, 2, 15), regime)
        
        stats = overlay.get_stats()
        
        assert stats["enabled"] is True
        assert stats["regime_changes"] == 1
        assert stats["rebalances"] == 2
        assert stats["days_risk_on"] == 1
        assert stats["days_risk_off"] == 1
    
    def test_disabled_overlay_always_returns_risk_on_asset(self):
        config = CrisisOverlayConfig(
            enabled=False,
            risk_on_asset="SPY",
            risk_off_asset="BIL",
        )
        overlay = CrisisOverlay(config)
        
        # Even in risk-off signal, should return risk-on asset when disabled
        overlay.current_regime = CrisisRegime.RISK_OFF
        assert overlay.get_target_allocation() == "SPY"
