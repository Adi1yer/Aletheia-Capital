"""Tests for edge gating and regime detection."""

from datetime import date, timedelta

import pytest

from src.backtesting.wheel_hybrid.iv_provider import (
    NullIVProvider,
    SyntheticIVFromRealizedProvider,
)
from src.backtesting.wheel_hybrid.edge_gate import EdgeGate, EdgeGateConfig
from src.backtesting.wheel_hybrid.regime import (
    RegimeDetector,
    RegimeConfig,
    RegimeState,
)


def test_null_iv_provider():
    """Test NullIVProvider returns None for all queries."""
    provider = NullIVProvider()
    
    assert provider.get_atm_iv("TEST", date.today(), 21) is None
    assert provider.get_iv_rank("TEST", date.today()) is None
    assert provider.get_iv_rv_spread("TEST", date.today(), 21, 0.20) is None


def test_synthetic_iv_provider():
    """Test SyntheticIVFromRealizedProvider adds premium bump."""
    
    def mock_rv_provider(symbol, as_of, window):
        return 0.20  # 20% realized vol
    
    provider = SyntheticIVFromRealizedProvider(
        realized_vol_provider=mock_rv_provider,
        premium_bump=0.15,  # +15% bump
    )
    
    # Synthetic IV should be RV * (1 + bump) = 0.20 * 1.15 = 0.23
    iv = provider.get_atm_iv("TEST", date.today(), 21)
    assert iv == pytest.approx(0.23)
    
    # VRP should equal the bump by construction
    vrp = provider.get_iv_rv_spread("TEST", date.today(), 21, 0.20)
    assert vrp == pytest.approx(0.15)
    
    # IV rank defaults to mean
    iv_rank = provider.get_iv_rank("TEST", date.today())
    assert iv_rank == 0.50


def test_edge_gate_disabled():
    """Test edge gate allows all writes when disabled."""
    provider = NullIVProvider()
    config = EdgeGateConfig(enabled=False)
    gate = EdgeGate(config, provider)
    
    # Should allow writes even with no IV
    allowed, reason = gate.should_write_cc("TEST", date.today(), 0.20)
    assert allowed
    assert reason == "gate_disabled"
    
    stats = gate.get_stats()
    assert stats["gate_enabled"] is False
    assert stats["writes_ungated"] == 1


def test_edge_gate_blocks_low_vrp():
    """Test edge gate blocks writes when VRP < threshold."""
    
    def mock_rv_provider(symbol, as_of, window):
        return 0.20  # 20% RV
    
    # Synthetic IV with only +5% bump → VRP = 5%
    provider = SyntheticIVFromRealizedProvider(
        realized_vol_provider=mock_rv_provider,
        premium_bump=0.05,
    )
    
    # Gate requires VRP > 10%
    config = EdgeGateConfig(
        enabled=True,
        min_vrp=0.10,
        fail_closed_when_no_iv=False,
    )
    gate = EdgeGate(config, provider)
    
    # Should block (VRP 5% < 10% threshold)
    allowed, reason = gate.should_write_cc("TEST", date.today(), 0.20)
    assert not allowed
    assert "vrp_too_low" in reason
    
    stats = gate.get_stats()
    assert stats["writes_blocked_vrp"] == 1
    assert stats["writes_allowed"] == 0


def test_edge_gate_allows_rich_vrp():
    """Test edge gate allows writes when VRP > threshold."""
    
    def mock_rv_provider(symbol, as_of, window):
        return 0.20  # 20% RV
    
    # Synthetic IV with +20% bump → VRP = 20%
    provider = SyntheticIVFromRealizedProvider(
        realized_vol_provider=mock_rv_provider,
        premium_bump=0.20,
    )
    
    # Gate requires VRP > 10%
    config = EdgeGateConfig(
        enabled=True,
        min_vrp=0.10,
        fail_closed_when_no_iv=False,
    )
    gate = EdgeGate(config, provider)
    
    # Should allow (VRP 20% > 10% threshold)
    allowed, reason = gate.should_write_cc("TEST", date.today(), 0.20)
    assert allowed
    assert "edge_detected" in reason
    
    stats = gate.get_stats()
    assert stats["writes_allowed"] == 1
    assert stats["writes_blocked_vrp"] == 0


def test_edge_gate_fail_closed_no_iv():
    """Test edge gate blocks writes when IV unavailable and fail_closed=True."""
    provider = NullIVProvider()  # Returns None
    
    config = EdgeGateConfig(
        enabled=True,
        min_vrp=0.10,
        fail_closed_when_no_iv=True,  # Fail safe
    )
    gate = EdgeGate(config, provider)
    
    # Should block (no IV data)
    allowed, reason = gate.should_write_cc("TEST", date.today(), 0.20)
    assert not allowed
    assert reason == "no_iv_data"
    
    stats = gate.get_stats()
    assert stats["writes_blocked_no_iv"] == 1


def test_edge_gate_fallback_no_iv():
    """Test edge gate allows writes when IV unavailable and fail_closed=False."""
    provider = NullIVProvider()
    
    config = EdgeGateConfig(
        enabled=True,
        min_vrp=0.10,
        fail_closed_when_no_iv=False,  # Fallback to legacy
    )
    gate = EdgeGate(config, provider)
    
    # Should allow (fallback mode)
    allowed, reason = gate.should_write_cc("TEST", date.today(), 0.20)
    assert allowed
    assert "unavailable_fallback" in reason


def test_regime_detector_disabled():
    """Test regime detector returns HARVEST_VRP when disabled."""
    provider = NullIVProvider()
    config = RegimeConfig(enabled=False)
    detector = RegimeDetector(config, provider)
    
    regime = detector.update(date.today(), vrp_avg=0.05, rv_avg=0.15)
    assert regime == RegimeState.HARVEST_VRP
    
    assert detector.should_write_cc() is True  # Always allow when disabled


def test_regime_detector_harvest_vrp():
    """Test regime detector enters HARVEST_VRP when VRP > threshold."""
    provider = NullIVProvider()
    config = RegimeConfig(
        enabled=True,
        harvest_min_vrp=0.20,
        hold_max_vrp=0.10,
    )
    detector = RegimeDetector(config, provider)
    
    # High VRP (25%) → HARVEST_VRP
    for _ in range(5):  # Confirm over multiple days
        regime = detector.update(date.today(), vrp_avg=0.25, rv_avg=0.20)
    
    assert regime == RegimeState.HARVEST_VRP
    assert detector.should_write_cc() is True


def test_regime_detector_hold_delta():
    """Test regime detector enters HOLD_DELTA when VRP < threshold."""
    provider = NullIVProvider()
    config = RegimeConfig(
        enabled=True,
        harvest_min_vrp=0.20,
        hold_max_vrp=0.10,
        min_days_in_regime=3,
    )
    detector = RegimeDetector(config, provider)
    
    # Start in HARVEST_VRP
    assert detector.get_current_regime() == RegimeState.HARVEST_VRP
    
    # Low VRP (5%) → should transition to HOLD_DELTA after 3 days
    for i in range(5):
        regime = detector.update(date.today() + timedelta(days=i), vrp_avg=0.05, rv_avg=0.15)
    
    assert regime == RegimeState.HOLD_DELTA
    assert detector.should_write_cc() is False  # Skip CC in HOLD_DELTA


def test_regime_detector_defensive():
    """Test regime detector enters DEFENSIVE on vol spike."""
    provider = NullIVProvider()
    config = RegimeConfig(
        enabled=True,
        defensive_rv_spike=0.40,
        min_days_in_regime=2,
    )
    detector = RegimeDetector(config, provider)
    
    # Realized vol spike (50%) → DEFENSIVE
    for i in range(3):
        regime = detector.update(
            date.today() + timedelta(days=i),
            vrp_avg=0.15,
            rv_avg=0.50,  # High vol spike
        )
    
    assert regime == RegimeState.DEFENSIVE
    assert detector.should_write_cc() is False  # Reduce risk


def test_regime_detector_hysteresis():
    """Test regime detector requires min_days confirmation before switching."""
    provider = NullIVProvider()
    config = RegimeConfig(
        enabled=True,
        harvest_min_vrp=0.20,
        hold_max_vrp=0.10,
        min_days_in_regime=3,  # Require 3 days
    )
    detector = RegimeDetector(config, provider)
    
    # Start in HARVEST_VRP
    assert detector.get_current_regime() == RegimeState.HARVEST_VRP
    
    # Low VRP for only 2 days → should NOT switch yet
    for i in range(2):
        regime = detector.update(
            date.today() + timedelta(days=i),
            vrp_avg=0.05,
            rv_avg=0.15,
        )
    
    assert regime == RegimeState.HARVEST_VRP  # Still in HARVEST
    
    # One more day → now switch
    regime = detector.update(
        date.today() + timedelta(days=2),
        vrp_avg=0.05,
        rv_avg=0.15,
    )
    
    assert regime == RegimeState.HOLD_DELTA  # Switched after 3 days


def test_regime_stats():
    """Test regime detector tracks statistics."""
    provider = NullIVProvider()
    config = RegimeConfig(enabled=True, min_days_in_regime=1)
    detector = RegimeDetector(config, provider)
    
    # Spend 3 days in HARVEST
    for i in range(3):
        detector.update(date.today() + timedelta(days=i), vrp_avg=0.25, rv_avg=0.20)
    
    # Switch to HOLD for 2 days
    for i in range(3, 5):
        detector.update(date.today() + timedelta(days=i), vrp_avg=0.05, rv_avg=0.15)
    
    stats = detector.get_stats()
    assert stats["current_regime"] == "hold_delta"
    assert stats["days_in_harvest"] == 3
    assert stats["days_in_hold"] == 2
    assert stats["regime_transitions"] >= 1  # At least one transition
