"""Tests for directional trend/momentum overlay."""

import pytest
from datetime import date

from src.backtesting.wheel_hybrid.directional_trend import (
    DirectionalTrendOverlay,
    TrendConfig,
    calculate_relative_strength,
)


def test_trend_config_defaults():
    """Test default TrendConfig initialization."""
    config = TrendConfig()
    
    assert config.enabled is True
    assert config.sma_window == 200
    assert config.use_dual_momentum is True
    assert config.momentum_lookback == 126
    assert config.cash_when_bearish is True
    assert len(config.relative_strength_universe) > 0


def test_should_hold_directional_bullish():
    """Test should_hold_directional with bullish trend (price > SMA200)."""
    config = TrendConfig(enabled=True, sma_window=200)
    overlay = DirectionalTrendOverlay(config)
    
    # Create price history with uptrend
    price_history = [100.0] * 200  # Flat at 100
    current_price = 110.0  # Above SMA200 (100)
    
    should_hold, reason = overlay.should_hold_directional(
        "TEST", current_price, price_history, date(2024, 1, 1)
    )
    
    assert should_hold is True
    assert reason == "above_sma200"


def test_should_hold_directional_bearish():
    """Test should_hold_directional with bearish trend (price < SMA200)."""
    config = TrendConfig(enabled=True, sma_window=200, cash_when_bearish=True)
    overlay = DirectionalTrendOverlay(config)
    
    # Create price history with downtrend
    price_history = [100.0] * 200  # Flat at 100
    current_price = 90.0  # Below SMA200 (100)
    
    should_hold, reason = overlay.should_hold_directional(
        "TEST", current_price, price_history, date(2024, 1, 1)
    )
    
    assert should_hold is False
    assert reason == "below_sma200"


def test_should_hold_directional_insufficient_history():
    """Test should_hold_directional with insufficient price history."""
    config = TrendConfig(enabled=True, sma_window=200)
    overlay = DirectionalTrendOverlay(config)
    
    # Only 50 days of history (< 200 required)
    price_history = [100.0] * 50
    current_price = 110.0
    
    should_hold, reason = overlay.should_hold_directional(
        "TEST", current_price, price_history, date(2024, 1, 1)
    )
    
    assert should_hold is True
    assert reason == "insufficient_history"


def test_rank_directional_candidates():
    """Test rank_directional_candidates with momentum scoring."""
    config = TrendConfig(
        enabled=True,
        sma_window=200,
        use_dual_momentum=True,
        momentum_lookback=126,
    )
    overlay = DirectionalTrendOverlay(config)
    
    # Create test data
    candidates = ["TICKER_A", "TICKER_B", "TICKER_C"]
    
    # TICKER_A: strong uptrend
    history_a = [100.0] * 126 + [100.0] * 74  # 200 total
    history_a[-1] = 150.0  # Current price
    
    # TICKER_B: weak uptrend
    history_b = [100.0] * 126 + [100.0] * 74
    history_b[-1] = 105.0
    
    # TICKER_C: downtrend
    history_c = [100.0] * 126 + [100.0] * 74
    history_c[-1] = 90.0
    
    prices = {
        "TICKER_A": 150.0,
        "TICKER_B": 105.0,
        "TICKER_C": 90.0,
    }
    
    price_histories = {
        "TICKER_A": history_a,
        "TICKER_B": history_b,
        "TICKER_C": history_c,
    }
    
    ranked = overlay.rank_directional_candidates(
        candidates, prices, price_histories, date(2024, 1, 1)
    )
    
    # Should be ranked: A (strongest), B (weak), C (bearish)
    assert len(ranked) == 3
    assert ranked[0][0] == "TICKER_A"  # Best momentum
    assert ranked[0][1] > ranked[1][1]  # Score A > B
    assert ranked[1][1] > ranked[2][1]  # Score B > C
    assert ranked[2][1] < 0  # C is negative (bearish)


def test_filter_directional_universe():
    """Test filter_directional_universe to exclude bearish tickers."""
    config = TrendConfig(enabled=True, sma_window=200, cash_when_bearish=True)
    overlay = DirectionalTrendOverlay(config)
    
    universe = ["BULL", "BEAR", "FLAT"]
    
    # BULL: strong uptrend
    history_bull = [100.0] * 200
    price_bull = 120.0
    
    # BEAR: downtrend
    history_bear = [100.0] * 200
    price_bear = 80.0
    
    # FLAT: neutral
    history_flat = [100.0] * 200
    price_flat = 100.1
    
    prices = {
        "BULL": price_bull,
        "BEAR": price_bear,
        "FLAT": price_flat,
    }
    
    price_histories = {
        "BULL": history_bull,
        "BEAR": history_bear,
        "FLAT": history_flat,
    }
    
    filtered = overlay.filter_directional_universe(
        universe, prices, price_histories, date(2024, 1, 1)
    )
    
    # Should only include BULL and FLAT (price >= SMA200)
    assert len(filtered) == 2
    assert "BULL" in filtered
    assert "FLAT" in filtered
    assert "BEAR" not in filtered


def test_calculate_relative_strength():
    """Test calculate_relative_strength vs benchmarks."""
    # Ticker history: 100 -> 120 (+20%)
    ticker_history = [100.0] * 50 + [120.0] * 76  # 126 total
    
    # Benchmark 1: 100 -> 110 (+10%)
    bench1_history = [100.0] * 50 + [110.0] * 76
    
    # Benchmark 2: 100 -> 105 (+5%)
    bench2_history = [100.0] * 50 + [105.0] * 76
    
    benchmarks = {
        "BENCH1": bench1_history,
        "BENCH2": bench2_history,
    }
    
    # Average benchmark return = (10% + 5%) / 2 = 7.5%
    # Relative strength = 20% - 7.5% = 12.5% = 0.125
    
    rs = calculate_relative_strength("TICKER", ticker_history, benchmarks, 126)
    
    assert rs > 0.10  # Outperforming benchmarks
    assert rs < 0.15  # Reasonable range


def test_trend_overlay_disabled():
    """Test that overlay does nothing when disabled."""
    config = TrendConfig(enabled=False)
    overlay = DirectionalTrendOverlay(config)
    
    # Should always return True (hold) when disabled
    should_hold, reason = overlay.should_hold_directional(
        "TEST", 50.0, [100.0] * 200, date(2024, 1, 1)
    )
    
    assert should_hold is True
    assert reason == "trend_overlay_disabled"


def test_get_stats():
    """Test get_stats returns expected structure."""
    config = TrendConfig()
    overlay = DirectionalTrendOverlay(config)
    
    # Simulate some regime tracking
    overlay.update_regime(True)
    overlay.update_regime(True)
    overlay.update_regime(False)
    
    stats = overlay.get_stats()
    
    assert stats["days_risk_on"] == 2
    assert stats["days_risk_off"] == 1
    assert stats["total_days"] == 3
    assert stats["risk_on_pct"] == pytest.approx(66.67, abs=0.1)
    assert "config" in stats
    assert stats["config"]["enabled"] is True
